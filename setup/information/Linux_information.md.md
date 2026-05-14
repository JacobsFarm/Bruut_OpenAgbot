finding the Linux connected boards

command ls /dev/ttyACM* 

Wanneer permission denied geef jezelf toegang tot de poort 

sudo usermod -a -G dialout $USER

of geforceerd open zetten

sudo chmod 666 /dev/ttyACM1

inplaats van python roep je in linux/ubuntu python3 op