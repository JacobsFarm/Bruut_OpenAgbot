finding the Linux connected boards

command ls /dev/ttyACM* 

Wanneer permission denied geef jezelf toegang tot de poort 

sudo usermod -a -G dialout $USER

of geforceerd open zetten

sudo chmod 666 /dev/ttyACM1

inplaats van python roep je in linux/ubuntu python3 op

sh: 1: vite: Permission denied *fix*
chmod -R +x node_modules/.bin

Vinden van de USB poorten op de jetson 
 ls /dev/ttyACM* /dev/ttyUSB*

ls -l /dev/serial/by-id/

ls -l /dev/ttyACM*

udevadm info -n /dev/ttyACM3 | grep ID_MODEL_ID

Of de hele tekst

jetson@jetson-desktop:~$ ls -l /dev/ttyACM*
crw-rw---- 1 root dialout 166, 0 jun  4 23:46 /dev/ttyACM0
crw-rw---- 1 root dialout 166, 1 jan  1  1970 /dev/ttyACM1
crw-rw---- 1 root dialout 166, 2 jan  1  1970 /dev/ttyACM2
crw-rw---- 1 root dialout 166, 3 jun  5 09:39 /dev/ttyACM3
jetson@jetson-desktop:~$ udevadm info -n /dev/ttyACM0 | grep ID_MODEL_ID
E: ID_MODEL_ID=01ab
jetson@jetson-desktop:~$ udevadm info -n /dev/ttyACM1 | grep ID_MODEL_ID
E: ID_MODEL_ID=01a9
jetson@jetson-desktop:~$ udevadm info -n /dev/ttyACM21 | grep ID_MODEL_ID
Unknown device "/dev/ttyACM21": No such file or directory
jetson@jetson-desktop:~$ udevadm info -n /dev/ttyACM2 | grep ID_MODEL_ID
E: ID_MODEL_ID=1002
jetson@jetson-desktop:~$ udevadm info -n /dev/ttyACM3 | grep ID_MODEL_ID
E: ID_MODEL_ID=0069
jetson@jetson-desktop:~$ ls -l /dev/serial/by-id/
total 0
lrwxrwxrwx 1 root root 13 jun  5 09:39 usb-Arduino_UNO_R4_Minima_320B2D1839313139DD3033354B57336E-if00 -> ../../ttyACM3
lrwxrwxrwx 1 root root 13 jan  1  1970 usb-Arduino_UNO_WiFi_R4_CMSIS-DAP_F412FA75D878-if01 -> ../../ttyACM2
lrwxrwxrwx 1 root root 13 jan  1  1970 usb-u-blox_AG_-_www.u-blox.com_u-blox_GNSS_receiver-if00 -> ../../ttyACM0
jetson@jetson-desktop:~$ ls -l /dev/ttyACM*      
*
