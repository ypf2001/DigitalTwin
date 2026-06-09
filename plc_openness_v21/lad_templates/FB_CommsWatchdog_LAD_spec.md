# FB_CommsWatchdog_LAD Template Spec

Create this block manually once in TIA Portal as a LAD FB:

```text
FB_CommsWatchdog_LAD
```

## Interface

Inputs:

```text
Remote_Heartbeat : Int
```

Outputs:

```text
Remote_Comms_OK : Bool
Watchdog_Timer : Int
```

Static:

```text
Last_Heartbeat : Int
Heartbeat_Changed : Bool
tWatchdog : TON_TIME
```

## Network 1

Title:

```text
Heartbeat changed
```

Logic:

```text
Remote_Heartbeat <> Last_Heartbeat -> Heartbeat_Changed
```

LAD elements:

```text
NE / <> comparator
IN1 := Remote_Heartbeat
IN2 := Last_Heartbeat
OUT := Heartbeat_Changed
```

## Network 2

Title:

```text
Store heartbeat
```

Logic:

```text
Heartbeat_Changed -> MOV Remote_Heartbeat to Last_Heartbeat
```

LAD elements:

```text
NO contact: Heartbeat_Changed
MOVE
IN  := Remote_Heartbeat
OUT := Last_Heartbeat
```

## Network 3

Title:

```text
Communication watchdog
```

Logic:

```text
NOT Heartbeat_Changed -> TON 3s
```

LAD elements:

```text
NC contact: Heartbeat_Changed
TON instance: tWatchdog
IN := NOT Heartbeat_Changed
PT := T#3s
ET -> Watchdog_Timer if needed
```

If TIA does not allow direct `ET -> Int`, leave `Watchdog_Timer` unused here or convert ET separately.

## Network 4

Title:

```text
Communication OK
```

Logic:

```text
NOT tWatchdog.Q -> Remote_Comms_OK
```

LAD elements:

```text
NC contact: tWatchdog.Q
Coil: Remote_Comms_OK
```

## After Drawing

Export this block with:

```powershell
cd "D:\Digital Twin\plc_openness_v21"

python .\examples\export_lad_template.py `
  --project "D:\dw_plc\xiaweiji\xiaweiji.ap21" `
  --plc "PLC_1" `
  --block "FB_CommsWatchdog_LAD" `
  --output ".\lad_templates\FB_CommsWatchdog_LAD.xml"
```

After that, Python can copy and parameterize this LAD block through Openness.
