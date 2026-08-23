# Bruut_OpenAgbot
Project for making the Bruut_OpenAgbot 

Follow along the project on youtube: https://www.youtube.com/@opensource_agbot/videos
Visit the website for more information https://jacobsfarm.github.io/Bruut_openagbot_website/ 

newest configuration the 2WD: 
<img width="4000" height="2250" alt="DJI_0515" src="https://github.com/user-attachments/assets/65ba3379-2303-49a0-9600-235584ea8edb" />
<img width="4080" height="3072" alt="PXL_20260816_183624926" src="https://github.com/user-attachments/assets/c81b0a46-ca6d-4342-92a0-46ce6de51545" />


This repo contains all the code information and code for the Agbot bruut Project 
The first runs for the prototype wil be used code in Python, C++ and the front end bases on svelte
later the project wil immigrate to ROS 2 and Floxglove 

## openscad project
New cad designs after testing in the Field, stronger and more realistic designs and even more oppertunity for extensions

<img width="2380" height="1792" alt="Gemini_Generated_Image_6x3t376x3t376x3t" src="https://github.com/user-attachments/assets/882ea169-424b-40ec-9939-3123089498dc" />
<img width="4080" height="3072" alt="PXL_20260816_183617888(1)" src="https://github.com/user-attachments/assets/71f47128-760a-4249-89a0-035e53f4c85b" />

**4 wheeldrive designs** with 4 electric driven hubmotors
<img width="670" height="468" alt="Schermafbeelding 2026-05-24 135653" src="https://github.com/user-attachments/assets/44cab0dc-73f4-4b09-ba7e-08376c236620" />
<img width="701" height="427" alt="Schermafbeelding 2026-05-24 135643" src="https://github.com/user-attachments/assets/61b133ca-1d35-43e1-92d8-34c8fd26ee93" />
<img width="703" height="398" alt="Schermafbeelding 2026-05-24 135613" src="https://github.com/user-attachments/assets/a1411bc4-7a87-401f-9826-5b742b8ba9f4" />
<img width="569" height="396" alt="Schermafbeelding 2026-05-24 135552" src="https://github.com/user-attachments/assets/9eaf7c64-82ae-4e81-a017-e2e662b4b611" />

**2 wheeldrive designs** difference is 2 wheel casters in the back
<img width="647" height="568" alt="Schermafbeelding 2026-05-24 223704" src="https://github.com/user-attachments/assets/f357dc0f-3353-4115-96fc-2df9d8215177" />
<img width="687" height="591" alt="Schermafbeelding 2026-05-24 223727" src="https://github.com/user-attachments/assets/7ee337e6-564b-467f-88c6-9d8ea53cddcc" />


## Options 
making taskcards of the detection of diseases / birdnests or Sprayed weed
<img width="1904" height="628" alt="Schermafbeelding 2026-04-26 231133" src="https://github.com/user-attachments/assets/24dcf64c-6d9d-4f07-83c4-480092d47888" />


## AB-line missions

Autonomous field work runs on AB lines. You measure two points with the RTK:
**A = the bottom-left corner** of the field and **B = the top-left corner**.
Together they set the direction and the length of the swaths.

Build the mission with a single script:

```bash
python Single_script_code/AB_mission_maker.py
```

Set the field name, the two points, the work width and the number of swaths at
the top of the script. It writes the mission into `data/ab_line.json` and draws
a preview: `ab_missie.jpg` (field sketch in metres), `ab_missie_gps.jpg` (same mission in lat/lon) and `ab_missie.html` (interactive satellite map)
so you can check the headlands before driving.

The script plans a **skip pass** order: on the way out it skips a swath every
time (0, 2, 4, 6) and on the way back it fills the gaps (7, 5, 3, 1). The side
step at almost every headland turn is then twice the work width, which is
exactly what a four-wheeler needs - a half circle of twice the minimum turning
radius fits. Only at the turning point of the pattern (6 -> 7) do two swaths sit
next to each other; there the robot drives an omega turn instead.

At the end of a swath the robot keeps going straight for `kopakker_extra_m`
(2 m by default) into the headland before it turns. The turn is built so that it
ends at exactly the same distance along the line as where it started, so after
the turn the robot has that same 2 m of straight run-in to settle dead straight
on the new line before the crop begins.

Pick the field in the web interface under **Landbouw** and press start.
