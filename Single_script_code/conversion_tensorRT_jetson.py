from ultralytics import YOLO

# Gebruik het model dat je wilt converteren
model = YOLO('model.pt') 

# Export naar TensorRT
model.export(
    format="engine",
    imgsz=640,      
    half=True,      
    device=0,       
    workspace=1,    
    batch=1         
)