import os
import shutil

# ==========================================
#                PARAMETERS
# ==========================================
# IMPORTANT: Update these paths to match your local directory structure before running!

# The main folder containing all subfolders to process
SOURCE_FOLDER = r"C:\path\to\your\data\To_extract"

# The 3 target folders
TARGET_CLEAN = r"C:\path\to\your\data\clean"           # Folder for all clean.jpg files
TARGET_CONF = r"C:\path\to\your\data\conf"             # Folder for all _conf... files
TARGET_CONF_JSON = r"C:\path\to\your\data\gps"         # Folder for _conf... files AND metadata.json

# ==========================================

def sort_files():
    """
    Scans the source folder for subfolders, extracts specific files 
    (clean images, confidence images, and metadata), and copies them 
    to designated target folders with a folder-name prefix.
    """
    # 1. Create the target folders if they do not exist yet
    for directory_path in [TARGET_CLEAN, TARGET_CONF, TARGET_CONF_JSON]:
        if not os.path.exists(directory_path):
            os.makedirs(directory_path)
            print(f"Created directory: {directory_path}")

    # Check if the source folder actually exists before proceeding
    if not os.path.exists(SOURCE_FOLDER):
        print(f"Error: Source folder '{SOURCE_FOLDER}' does not exist. Please check the path configuration.")
        return

    # 2. Loop through all items in the source folder
    for folder_name in os.listdir(SOURCE_FOLDER):
        folder_path = os.path.join(SOURCE_FOLDER, folder_name)

        # Check if the current item is actually a directory
        if os.path.isdir(folder_path):
            files = os.listdir(folder_path)

            # Temporary variables to store matched files in this subfolder
            clean_img = None
            conf_img = None
            json_file = None

            # Look for the specific files in the subfolder
            for file in files:
                filename_lower = file.lower()
                if filename_lower == "clean.jpg":
                    clean_img = file
                elif "_conf" in filename_lower and filename_lower.endswith((".jpg", ".jpeg", ".png")):
                    conf_img = file
                elif filename_lower == "metadata.json":
                    json_file = file

            # -- COPY LOGIC --
            
            # Target 1: Copy clean.jpg to TARGET_CLEAN
            if clean_img:
                source_path = os.path.join(folder_path, clean_img)
                target_path = os.path.join(TARGET_CLEAN, f"{folder_name}_{clean_img}")
                shutil.copy2(source_path, target_path)

            # Target 2 & 3: Copy _conf file to TARGET_CONF AND TARGET_CONF_JSON
            if conf_img:
                source_path = os.path.join(folder_path, conf_img)
                
                # Copy to Target 2
                target_path_2 = os.path.join(TARGET_CONF, f"{folder_name}_{conf_img}")
                shutil.copy2(source_path, target_path_2)
                
                # Copy to Target 3
                target_path_3 = os.path.join(TARGET_CONF_JSON, f"{folder_name}_{conf_img}")
                shutil.copy2(source_path, target_path_3)

            # Target 3: Copy metadata.json to TARGET_CONF_JSON
            if json_file:
                source_path = os.path.join(folder_path, json_file)
                target_path = os.path.join(TARGET_CONF_JSON, f"{folder_name}_{json_file}")
                shutil.copy2(source_path, target_path)
                
    print("\n✅ Copying complete! All files have been successfully sorted.")

if __name__ == "__main__":
    sort_files()