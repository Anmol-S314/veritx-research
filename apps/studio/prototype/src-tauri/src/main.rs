#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::{
    fs::{self, OpenOptions},
    io::{BufRead, BufReader},
    process::{Child, Command, Stdio},
    sync::{mpsc, Mutex},
    thread,
    time::{Duration, Instant},
};
use tauri::Manager;

#[derive(Clone, Deserialize, Serialize)]
struct Connection {
    base: String,
}

struct Backend {
    child: Child,
    connection: Connection,
}

impl Drop for Backend {
    fn drop(&mut self) {
        // Closing stdin also tells the server to stop if signalling fails.
        self.child.stdin.take();
        #[cfg(unix)]
        unsafe {
            libc::kill(-(self.child.id() as i32), libc::SIGTERM);
        }
        let deadline = Instant::now() + Duration::from_secs(8);
        let mut exited = false;
        while Instant::now() < deadline {
            if matches!(self.child.try_wait(), Ok(Some(_))) {
                exited = true;
                break;
            }
            thread::sleep(Duration::from_millis(50));
        }
        if !exited {
            #[cfg(unix)]
            unsafe {
                libc::kill(-(self.child.id() as i32), libc::SIGKILL);
            }
            let _ = self.child.kill();
        }
        let _ = self.child.wait();
    }
}

fn start_backend(app: &tauri::App) -> Result<Backend, Box<dyn std::error::Error>> {
    let data_dir = app.path().app_local_data_dir()?;
    fs::create_dir_all(&data_dir)?;
    let log_path = data_dir.join("backend.log");
    let log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)?;

    #[cfg(debug_assertions)]
    let mut command = {
        let prototype = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap();
        let local_python = prototype.join(if cfg!(windows) {
            ".desktop-venv/Scripts/python.exe"
        } else {
            ".desktop-venv/bin/python"
        });
        let python = std::env::var_os("SROTA_PYTHON").unwrap_or_else(|| {
            if local_python.is_file() {
                local_python.into_os_string()
            } else {
                if cfg!(windows) { "python" } else { "python3" }.into()
            }
        });
        let mut cmd = Command::new(python);
        cmd.arg(prototype.join("desktop/gateway.py"));
        cmd
    };
    #[cfg(not(debug_assertions))]
    let mut command = {
        // The frozen gateway ships as a one-dir tree under the app resources:
        // its own _internal directory sits next to the launcher, so launch does
        // no archive extraction.
        let gateway = app
            .path()
            .resolve("gateway", tauri::path::BaseDirectory::Resource)?;
        let executable = gateway.join(if cfg!(windows) {
            "srota-gateway.exe"
        } else {
            "srota-gateway"
        });
        if !executable.is_file() {
            return Err(format!("Bundled gateway is missing at {}", executable.display()).into());
        }
        Command::new(executable)
    };

    command
        .args(["--data-dir"])
        .arg(&data_dir)
        .current_dir(&data_dir)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::from(log));
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // The owned gateway communicates through pipes, not a console window.
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    let child = command.spawn()?;
    let mut backend = Backend {
        child,
        connection: Connection {
            base: String::new(),
        },
    };
    let stdout = backend.child.stdout.take().unwrap();
    let (sender, receiver) = mpsc::sync_channel(1);
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Some(json) = line.strip_prefix("SROTA_READY ") {
                // Only one startup announcement is expected; drain any later output.
                let _ = sender.try_send(serde_json::from_str::<Connection>(json));
            }
        }
    });
    let connection = receiver
        .recv_timeout(Duration::from_secs(120))
        .map_err(|_| format!("Backend did not start. Inspect {}", log_path.display()))??;
    let url = tauri::Url::parse(&connection.base)?;
    if url.scheme() != "http" || url.host_str() != Some("127.0.0.1") || url.port().is_none() {
        return Err("Backend returned an invalid local address".into());
    }
    backend.connection = connection;
    Ok(backend)
}

#[tauri::command]
fn gateway_connection(
    backend: tauri::State<'_, Mutex<Option<Backend>>>,
) -> Result<Connection, String> {
    backend
        .lock()
        .map_err(|_| "Backend state unavailable")?
        .as_ref()
        .map(|backend| backend.connection.clone())
        .ok_or_else(|| "Backend is not running".into())
}

fn main() {
    let app = tauri::Builder::default()
        .setup(|app| {
            app.manage(Mutex::new(Some(start_backend(app)?)));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![gateway_connection])
        .build(tauri::generate_context!())
        .expect("Could not start Srota Studio");
    app.run(|app, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            let state = app.state::<Mutex<Option<Backend>>>();
            if let Ok(mut backend) = state.lock() {
                backend.take();
            };
        }
    });
}
