import threading
import time

class SkidsteerController:
    def __init__(self, motor_controller):
        self.motor_controller = motor_controller
        self.target_l = 700
        self.target_r = 700
        self.current_l = 700
        self.current_r = 700
        self.running = True
        
        # Instellingen voor een rustige rit
        self.dt = 0.1            # Snelheid van de loop (100ms)
        self.deadzone_jump = 1150 # Startwaarde om de dode zone te skippen
        
        # AGGRESSIE FACTOR (Pas dit aan om de rit te tunen):
        # Hoe lager dit getal (bijv. 0.15), hoe vloeiender/rustiger de acceleratie.
        # Hoe hoger dit getal (bijv. 0.40), hoe feller de robot reageert.
        self.smoothing_factor = 0.20 
        
        # Minimale en maximale stapgrootte per 100ms
        self.min_step = 25       # Zorgt voor zeer subtiele correcties bij lage snelheid
        self.max_step = 120      # Voorkomt dat de stappen té groot worden bij uitschieters

        # Start de achtergrond-loop
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def set_target(self, links, rechts):
        self.target_l = max(700, min(3100, int(links)))
        self.target_r = max(700, min(3100, int(rechts)))

    def stop_direct(self):
        self.target_l = 700
        self.target_r = 700
        self.current_l = 700
        self.current_r = 700
        self.motor_controller.stuur_motoren(700, 700, dwing_verzenden=True)

    def _bereken_volgende_stap(self, current, target):
        if current == target:
            return current
        
        # SITUATIE 1: Vanuit stilstand (700) gaan rijden
        if current == 700 and target > 700:
            # Spring direct naar de absolute ondergrens (dode zone voorbij)
            return min(target, self.deadzone_jump)
            
        # SITUATIE 2: We remmen af en zijn bijna bij de nulstand
        if target == 700 and current <= (self.deadzone_jump + 20):
            # Klap direct door naar de veilige ruststand (700)
            return 700

        # SITUATIE 3: Dynamische stappen berekenen op basis van het resterende verschil
        verschil = target - current
        
        # Bereken een stap die proportioneel is aan het verschil (bijv. 20% van de resterende afstand)
        berekende_stap = abs(verschil) * self.smoothing_factor
        
        # Begrens de berekende stap tussen onze veilige min/max limieten
        daadwerkelijke_stap = max(self.min_step, min(self.max_step, berekende_stap))
        
        # Voer de stap uit in de juiste richting
        if abs(verschil) <= daadwerkelijke_stap:
            return target
        elif verschil > 0:
            return int(current + daadwerkelijke_stap)
        else:
            return int(current - daadwerkelijke_stap)

    def _loop(self):
        while self.running:
            if self.current_l != self.target_l or self.current_r != self.target_r:
                self.current_l = self._bereken_volgende_stap(self.current_l, self.target_l)
                self.current_r = self._bereken_volgende_stap(self.current_r, self.target_r)
                
                # Stuur naar de hardware motor controller
                self.motor_controller.stuur_motoren(self.current_l, self.current_r)
            
            time.sleep(self.dt)