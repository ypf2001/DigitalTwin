# PLC Openness V21 Python Starter

This folder is a small Python starter project for Siemens TIA Portal V21 Openness.

It loads the V21 PublicAPI assemblies from:

```text
D:\Program Files\Siemens\Automation\Portal V21\PublicAPI\V21\net48
```

Main workflow:

1. Python writes or updates an SCL source file.
2. TIA Openness imports the source into the PLC external source group.
3. TIA Openness generates PLC blocks from that source.
4. Optionally compile the PLC software.

## Setup

Install Python dependency:

```powershell
cd "D:\Digital Twin\plc_openness_v21"
pip install -r requirements.txt
```

Make sure your Windows user is in the Siemens Openness group:

```powershell
net localgroup "Siemens TIA Openness"
```

If your user is missing, run PowerShell as administrator:

```powershell
net localgroup "Siemens TIA Openness" "%USERNAME%" /add
```

Then sign out or restart Windows.

## Smoke test

Start TIA Portal from Python:

```powershell
python .\examples\check_openness.py
```

## Import SCL into an existing project

Use an existing `.ap21` project that already contains an S7-1200 or S7-1500 CPU:

```powershell
python .\examples\import_scl_to_project.py --project "D:\TIAProjects\Demo\Demo.ap21" --source ".\plc_sources\ScaleAnalog.scl" --compile
```

If the project has several PLCs, choose one by name:

```powershell
python .\examples\import_scl_to_project.py --project "D:\TIAProjects\Demo\Demo.ap21" --plc "PLC_1" --source ".\plc_sources\ScaleAnalog.scl"
```

For the current PLC project at `D:\dw_plc\xiaweiji`, run:

```powershell
.\run_import_xiaweiji.ps1
```

That script imports:

```text
D:\dw_plc\xiaweiji\src\xiaweiji.scl
```

into:

```text
D:\dw_plc\xiaweiji\xiaweiji.ap21
```

## Create an empty TIA project

This creates a TIA project. Creating a CPU also needs the exact Siemens hardware type identifier for your PLC.

```powershell
python .\examples\create_project.py --directory "D:\TIAProjects" --name "PythonCreatedProject"
```

With a CPU type identifier:

```powershell
python .\examples\create_project.py --directory "D:\TIAProjects" --name "PythonCreatedProject" --cpu-name "PLC_1" --cpu-type "OrderNumber:6ES7..."
```

The CPU type identifier must match your installed hardware catalog.

## LAD template workflow

Use this when you want to draw a ladder block once in TIA Portal, then copy or parameterize it with Python.

### 1. Draw a LAD template in TIA

Create a LAD block manually in TIA Portal, for example:

```text
FB_LAD_Template
```

Use clear placeholder names inside the block if you plan to replace them later, for example:

```text
Pump_Template_Enable
Pump_Template_Output
FB_LAD_Template
```

### 2. Export the LAD block to XML

```powershell
python .\examples\export_lad_template.py `
  --project "D:\dw_plc\xiaweiji\xiaweiji.ap21" `
  --plc "PLC_1" `
  --block "FB_LAD_Template" `
  --output ".\lad_templates\FB_LAD_Template.xml"
```

The script attaches to the already-open TIA project if it is open.

### 3. Generate a new LAD XML from the template

```powershell
python .\examples\generate_lad_from_template.py `
  --template ".\lad_templates\FB_LAD_Template.xml" `
  --output ".\generated_lad\FB_Pump_01.xml" `
  --replace "FB_LAD_Template=FB_Pump_01" `
  --replace "Pump_Template_Enable=Pump_01_Enable" `
  --replace "Pump_Template_Output=Pump_01_Output"
```

For many replacements, use a JSON file:

```json
{
  "FB_LAD_Template": "FB_Pump_01",
  "Pump_Template_Enable": "Pump_01_Enable",
  "Pump_Template_Output": "Pump_01_Output"
}
```

Then run:

```powershell
python .\examples\generate_lad_from_template.py `
  --template ".\lad_templates\FB_LAD_Template.xml" `
  --output ".\generated_lad\FB_Pump_01.xml" `
  --replace-json ".\generated_lad\FB_Pump_01.replacements.json"
```

### 4. Import the generated LAD XML

Make sure TIA Portal is offline. Openness cannot import blocks while the project is online.

```powershell
python .\examples\import_lad_xml.py `
  --project "D:\dw_plc\xiaweiji\xiaweiji.ap21" `
  --plc "PLC_1" `
  --xml ".\generated_lad\FB_Pump_01.xml" `
  --compile
```

This imports the LAD block, compiles PLC software, and saves the project.
