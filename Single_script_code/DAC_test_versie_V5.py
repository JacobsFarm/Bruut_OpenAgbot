import customtkinter as ctk
import serial
import time

# --- INSTELLINGEN ---
COM_PORT = "COM3"  # Pas dit aan naar jouw poort
BAUD_RATE = 115200

# Rate limiting instellingen
laatste_zend_tijd = 0
VERTRAGING = 0.05  # Maximaal 1x per 50 milliseconden verzenden (20Hz)

try:
    arduino = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
    time.sleep(2) 
    print(f"Succesvol verbonden met {COM_PORT}")
except Exception as e:
    print(f"Let op: Kan geen verbinding maken met Arduino: {e}")
    arduino = None

# --- VERZEND FUNCTIES ---
def stuur_data_naar_arduino(dac_links, dac_rechts, dwing_verzenden=False):
    global laatste_zend_tijd
    
    # Bereken voltages voor weergave
    volt_links = 0.77 + ((dac_links - 700) * (3.4 - 0.77) / (3100 - 700))
    volt_rechts = 0.77 + ((dac_rechts - 700) * (3.4 - 0.77) / (3100 - 700))
    
    # Update de labels direct
    label_links.configure(text=f"Linker Wiel - DAC: {dac_links}  |  Voltage: ~{volt_links:.2f}V")
    label_rechts.configure(text=f"Rechter Wiel - DAC: {dac_rechts}  |  Voltage: ~{volt_rechts:.2f}V")
    
    # Controleer of we data mogen sturen
    huidige_tijd = time.time()
    if dwing_verzenden or (huidige_tijd - laatste_zend_tijd) >= VERTRAGING:
        if arduino and arduino.is_open:
            commando = f"{dac_links},{dac_rechts}\n"
            arduino.write(commando.encode('utf-8'))
            laatste_zend_tijd = huidige_tijd

# --- EVENT HANDLERS (MUIS) ---
def handmatige_sliders_event(event=None):
    if switch_gekoppeld.get() == 0:
        dac_links = int(slider_links.get())
        dac_rechts = int(slider_rechts.get())
        stuur_data_naar_arduino(dac_links, dac_rechts)

def handmatige_sliders_losgelaten(event):
    if switch_gekoppeld.get() == 0:
        dac_links = int(slider_links.get())
        dac_rechts = int(slider_rechts.get())
        stuur_data_naar_arduino(dac_links, dac_rechts, dwing_verzenden=True)

def gekoppelde_bediening_event(event=None):
    if switch_gekoppeld.get() == 1:
        gas_waarde = int(slider_gas.get())
        stuur_waarde = int(slider_sturen.get())
        
        actief_gas = gas_waarde - 700
        
        # Bereken de balans
        if stuur_waarde < 0: # Naar links
            factor = 1.0 - (abs(stuur_waarde) / 100.0)
            dac_links = 700 + int(actief_gas * factor)
            dac_rechts = gas_waarde
        elif stuur_waarde > 0: # Naar rechts
            factor = 1.0 - (stuur_waarde / 100.0)
            dac_links = gas_waarde
            dac_rechts = 700 + int(actief_gas * factor)
        else: # Rechtdoor
            dac_links = gas_waarde
            dac_rechts = gas_waarde
            
        # Update de bovenste sliders visueel
        slider_links.set(dac_links)
        slider_rechts.set(dac_rechts)
        stuur_data_naar_arduino(dac_links, dac_rechts)

def gekoppelde_bediening_losgelaten(event=None):
    if switch_gekoppeld.get() == 1:
        stuur_data_naar_arduino(int(slider_links.get()), int(slider_rechts.get()), dwing_verzenden=True)

# --- EVENT HANDLERS (TOETSENBORD) ---
def toets_gas_omhoog(event):
    if switch_gekoppeld.get() == 1:
        huidig = slider_gas.get()
        nieuw = min(3100, huidig + 50)
        slider_gas.set(nieuw)
        gekoppelde_bediening_event()

def toets_gas_omlaag(event):
    if switch_gekoppeld.get() == 1:
        huidig = slider_gas.get()
        nieuw = max(700, huidig - 50)
        slider_gas.set(nieuw)
        gekoppelde_bediening_event()

def toets_stuur_links(event):
    if switch_gekoppeld.get() == 1:
        huidig = slider_sturen.get()
        nieuw = max(-100, huidig - 10)
        slider_sturen.set(nieuw)
        gekoppelde_bediening_event()

def toets_stuur_rechts(event):
    if switch_gekoppeld.get() == 1:
        huidig = slider_sturen.get()
        nieuw = min(100, huidig + 10)
        slider_sturen.set(nieuw)
        gekoppelde_bediening_event()

def toets_spatie_centreren(event):
    if switch_gekoppeld.get() == 1:
        slider_sturen.set(0)
        gekoppelde_bediening_event()
        stuur_data_naar_arduino(int(slider_links.get()), int(slider_rechts.get()), dwing_verzenden=True)

def toets_stuur_losgelaten(event):
    if switch_gekoppeld.get() == 1:
        stuur_data_naar_arduino(int(slider_links.get()), int(slider_rechts.get()), dwing_verzenden=True)

def toets_gas_losgelaten(event):
    if switch_gekoppeld.get() == 1:
        stuur_data_naar_arduino(int(slider_links.get()), int(slider_rechts.get()), dwing_verzenden=True)

# --- MODUS WISSELAAR & RESET ---
def wissel_modus():
    is_gekoppeld = switch_gekoppeld.get() == 1
    if is_gekoppeld:
        slider_links.configure(state="disabled")
        slider_rechts.configure(state="disabled")
        slider_gas.configure(state="normal")
        slider_sturen.configure(state="normal")
        gekoppelde_bediening_event()
    else:
        slider_gas.configure(state="disabled")
        slider_sturen.configure(state="disabled")
        slider_links.configure(state="normal")
        slider_rechts.configure(state="normal")

def reset_motoren(event=None): # Event=None toegevoegd voor de bind-compatibiliteit
    slider_links.configure(state="normal")
    slider_rechts.configure(state="normal")
    slider_links.set(700)
    slider_rechts.set(700)
    slider_gas.set(700)
    slider_sturen.set(0)
    
    wissel_modus()
    stuur_data_naar_arduino(700, 700, dwing_verzenden=True)
    print("NOODSTOP GEACTIVEERD: Motoren gereset.")

# --- GUI SETUP ---
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

app = ctk.CTk()
app.geometry("550x680")
app.title("Dual Hubmotor DAC Controller (Muis & Toetsenbord)")

titel = ctk.CTkLabel(app, text="Voertuig Besturing", font=("Arial", 20, "bold"))
titel.pack(pady=10)

# KOPPELING SCHAKELAAR
frame_schakelaar = ctk.CTkFrame(app)
frame_schakelaar.pack(pady=10, padx=20, fill="x")
switch_gekoppeld = ctk.CTkSwitch(frame_schakelaar, text="Gekoppelde Besturing (Muis & Pijltjes)", font=("Arial", 14, "bold"), command=wissel_modus)
switch_gekoppeld.pack(pady=15)
switch_gekoppeld.select()

# INDIVIDUELE WIELEN (BOVEN)
frame_wielen = ctk.CTkFrame(app, fg_color="transparent")
frame_wielen.pack(pady=5, padx=20, fill="x")

label_links = ctk.CTkLabel(frame_wielen, text="Linker Wiel - DAC: 700  |  Voltage: ~0.77V", font=("Arial", 14))
label_links.pack(pady=(0, 5))
slider_links = ctk.CTkSlider(frame_wielen, from_=700, to=3100, command=handmatige_sliders_event, height=25, button_length=25)
slider_links.set(700)
slider_links.pack(fill="x", pady=5)
slider_links.bind("<ButtonRelease-1>", handmatige_sliders_losgelaten)

label_rechts = ctk.CTkLabel(frame_wielen, text="Rechter Wiel - DAC: 700  |  Voltage: ~0.77V", font=("Arial", 14))
label_rechts.pack(pady=(15, 5))
slider_rechts = ctk.CTkSlider(frame_wielen, from_=700, to=3100, command=handmatige_sliders_event, height=25, button_length=25)
slider_rechts.set(700)
slider_rechts.pack(fill="x", pady=5)
slider_rechts.bind("<ButtonRelease-1>", handmatige_sliders_losgelaten)

ctk.CTkFrame(app, height=2, fg_color="gray").pack(pady=15, padx=40, fill="x")

# GEKOPPELDE BEDIENING (ONDER)
frame_gekoppeld = ctk.CTkFrame(app, fg_color="transparent")
frame_gekoppeld.pack(pady=5, padx=20, fill="x")

label_gas = ctk.CTkLabel(frame_gekoppeld, text="Hoofdgas (Pijltje Omhoog / Omlaag)", font=("Arial", 14, "bold"))
label_gas.pack(pady=(0, 5))
slider_gas = ctk.CTkSlider(frame_gekoppeld, from_=700, to=3100, command=gekoppelde_bediening_event, button_color="green", button_hover_color="darkgreen", height=35, button_length=35)
slider_gas.set(700)
slider_gas.pack(fill="x", pady=10)
slider_gas.bind("<ButtonRelease-1>", gekoppelde_bediening_losgelaten)

label_sturen = ctk.CTkLabel(frame_gekoppeld, text="Sturen (Pijltjes L/R) - Spatie is Rechtdoor", font=("Arial", 14, "bold"))
label_sturen.pack(pady=(15, 5))
slider_sturen = ctk.CTkSlider(frame_gekoppeld, from_=-100, to=100, command=gekoppelde_bediening_event, button_color="orange", button_hover_color="darkorange", height=35, button_length=35)
slider_sturen.set(0)
slider_sturen.pack(fill="x", pady=10)
slider_sturen.bind("<ButtonRelease-1>", gekoppelde_bediening_losgelaten)

# NOODSTOP KNOP
btn_reset = ctk.CTkButton(app, text="Noodstop / Alles naar 0 (Enter)", command=reset_motoren, fg_color="darkred", hover_color="red", height=40, font=("Arial", 14, "bold"))
btn_reset.pack(pady=20)

# --- KEYBOARD BINDINGS ---
app.bind("<Up>", toets_gas_omhoog)
app.bind("<Down>", toets_gas_omlaag)
app.bind("<Left>", toets_stuur_links)
app.bind("<Right>", toets_stuur_rechts)
app.bind("<space>", toets_spatie_centreren)

# Koppel ENTER aan de Noodstop (Beide Enter toetsen)
app.bind("<Return>", reset_motoren)
app.bind("<KP_Enter>", reset_motoren)

# Toetsen losgelaten
app.bind("<KeyRelease-Left>", toets_stuur_losgelaten)
app.bind("<KeyRelease-Right>", toets_stuur_losgelaten)
app.bind("<KeyRelease-Up>", toets_gas_losgelaten)
app.bind("<KeyRelease-Down>", toets_gas_losgelaten)

# Start de juiste weergave
wissel_modus()

def on_closing():
    if arduino and arduino.is_open:
        arduino.close()
    app.destroy()

app.protocol("WM_DELETE_WINDOW", on_closing)
app.mainloop()