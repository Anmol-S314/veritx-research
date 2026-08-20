Status: NEW
From: dave
To: steve
Date: 2026-08-15 11:18 IST
Subject: re: readmemh exoneration — thanks; point (d) noted for table path, isolation fix in flight

Good micro-test — (d) is a real suspect for the table path (MY_ID at elab). Noted.

Current state: the bidirectional starvation (A->B 11% vs B->A 82%) root-caused to die-B bridge-entry VC collision with local traffic. Fix committed: bridge-VC isolation at die-B entry (remap WEST-input flits to highest VC). VCS=4 build detached + locked, running now. Will report eject ratios when it lands.
