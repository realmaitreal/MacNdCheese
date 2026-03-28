GPTK (D3DMetal) Manual

To use the GPTK backend in MacNCheese, you need the Windows GPTK DLL files.

Required DLLs:
- dxgi.dll
- d3d11.dll
- d3d12.dll

Optional but recommended if present:
- d3d12core.dll
- d3d10core.dll

Steps:
1. Download the GPTK package you want to use.
2. Extract it somewhere on disk.
3. Find the folder that contains the Windows DLLs.
4. In MacNCheese, open Settings -> Setup.
5. Click "Import GPTK DLLs".
6. Select the extracted folder that contains the DLLs.
7. MacNCheese will copy the DLLs into its configured GPTK directory.

Expected target inside MacNCheese:
gptk/lib/wine/x86_64-windows/

After import, select:
Backend -> GPTK (D3DMetal)

Notes:
- GPTK backend needs the Windows DLLs, not only the .app bundle.
- If a game still fails, remove local DXVK patches first.
- MacNCheese will use WINEDLLOVERRIDES for dxgi/d3d11/d3d12.
