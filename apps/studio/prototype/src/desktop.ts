// Populated before App (and its gateway client) are imported.
export let desktopGatewayBase: string | undefined;

export async function initializeDesktop(): Promise<void> {
  if (!('__TAURI_INTERNALS__' in window)) return;
  const { invoke } = await import('@tauri-apps/api/core');
  const connection = await invoke<{ base: string }>('gateway_connection');
  const url = new URL(connection.base);
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1') {
    throw new Error('The desktop backend returned an invalid local address.');
  }
  desktopGatewayBase = connection.base;
}
