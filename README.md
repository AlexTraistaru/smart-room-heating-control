# Smart Room Heating Control

Python project for simulating and controlling a room heating installation (manual and automatic modes), with temperature regulation as the main objective and pressure valve control for the installation.

## Overview

This project simulates a room heating installation controlled through concurrent software tasks (threads).

The system supports:
- **manual mode**, where the user directly sets the heating power
- **automatic mode**, where the control logic adjusts heating power to maintain a target temperature

In addition to temperature regulation, the project also simulates **pressure behavior** in the installation and **pressure valve control** to keep the system within safe operating limits.

The implementation uses message queues and synchronized shared state between tasks/threads to model the behavior of a simple control system.

For additional details, implementation notes, and scenario explanations, see the included report:
- `Smart-Room-Heating-Control-Report.pdf` *(Romanian, university project report)*

## Main Features

- Room temperature simulation with multiple temperature sensors (thermocouple-like readings)
- Manual and automatic operating modes
- Automatic heating power computation based on temperature error
- Pressure simulation and monitoring
- Pressure valve control logic (safety/relief behavior)
- Concurrent task-based architecture using threads
- Inter-task communication using queues
- Shared-state synchronization using locks (`Lock`) and stop signaling (`Event`)
- Console command interface for runtime control

## Control / Task Architecture

The implementation models several logical tasks:

- **SW** – user interface / command input task
- **T** – periodic temperature acquisition task
- **S** – decision/control task (comfort evaluation + automatic power command)
- **P** – periodic pressure task (pressure update + valve action)

The tasks communicate through queues and coordinate using synchronized shared state.

## Supported Console Commands

- `a` – switch to automatic mode
- `m` – switch to manual mode
- `p <0..100>` – set manual heating power (percentage)
- `q` – stop the program

## Project Structure

- `heating_control.py` – main Python script (simulation + control logic + threads)
- `Smart-Room-Heating-Control-Report.pdf` – project report (Romanian)
- scenario screenshots/results:
  - `scenario-1.png`
  - `scenario-2.png`
  - `scenario-3.png`
  - `scenario-4.png`

## Requirements

- Python 3.x
- No external dependencies (uses only Python standard library modules)

## How to Run

1. Open a terminal in the project folder.
2. Run the script:

    python heating_control.py

3. Use the console commands to switch modes and control the system:
   - `a`
   - `m`
   - `p 80`
   - `q`

## Example Behavior

In automatic mode, the controller computes heating power based on the difference between:
- measured average temperature
- target/reference temperature

The pressure task updates the installation pressure periodically and opens the valve when pressure exceeds normal/safety thresholds.

## Scenario Screenshots and Validation Notes

The following screenshots illustrate tested operating scenarios from the project report (Chapter 4: testing and validation).  
A more detailed explanation is available in the included PDF report: `Smart-Room-Heating-Control-Report.pdf` *(Romanian)*.

### Scenario 1 — Automatic Mode: Temperature Stabilization and Power Adjustment

![Scenario 1](scenario-1.png)

In this scenario, the system runs in **automatic mode**, and task **S** computes the heating power based on the temperature error relative to the reference value.  
At the beginning, the average temperature is below the comfort zone, so the controller applies a higher heating power. As the temperature approaches the reference/comfort zone, the computed power gradually decreases. This demonstrates the expected stabilization behavior. :contentReference[oaicite:1]{index=1}

The report also notes that pressure remains around the reference value, while the pressure task **P** occasionally actuates the valve preventively when pressure exceeds the intermediate threshold. :contentReference[oaicite:2]{index=2}

---

### Scenario 2 — Switch to Manual Mode and Set Fixed Power (40%)

![Scenario 2](scenario-2.png)

This scenario validates the transition from **automatic** to **manual** mode.  
After the `m` command and setting `p 40`, the displayed heating power remains fixed at **40%** for multiple iterations, which confirms that task **S** no longer overrides the user command in manual mode. :contentReference[oaicite:3]{index=3}

---

### Scenario 3 — Pressure Safety Test in Manual Mode (`p 100`)

![Scenario 3](scenario-3.png)

This scenario tests a **maximum-stress / safety case**: the system is switched to manual mode and the user sets `p 100`.  
As expected, the average temperature increases significantly and the pressure rises toward the safety threshold. When pressure reaches the critical zone, task **P** opens the valve to **1.0** (maximum opening), showing that the safety mechanism activates correctly to prevent uncontrolled pressure growth. :contentReference[oaicite:5]{index=5}

---

### Scenario 4 — Return to Automatic Mode After Overheating

![Scenario 4](scenario-4.png)

This scenario validates recovery after overheating.  
After switching back to **automatic mode** (command `a`), task **S** resumes automatic control. Because the measured temperature is initially too high (`comfort = warm`), the computed heating power drops to **0%**, then increases gradually again as the temperature returns toward the comfort zone. :contentReference[oaicite:7]{index=7}

## Notes

- Some comments/identifiers in the source code may be in Romanian because the project was developed as part of university coursework.
- The included PDF report is also in Romanian, but it contains additional implementation details and scenario explanations.
- The code is kept in a single script for clarity and to preserve the original project structure.

## Author

**Alex Traistaru**  
Student, Automatic Control and Computers (UPB)
