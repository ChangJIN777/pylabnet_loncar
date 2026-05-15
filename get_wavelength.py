from pylabnet.network.client_server.high_finesse_ws7 import Client
import sys
sys.path.insert(0, r'C:\Users\User\Documents\pylabnet_loncar')


wlm = Client(host='192.168.50.105', port=10109)
for channel in range(1, 9):
    freq = wlm.get_wavelength(channel=channel)
    print(f'Channel {channel}: {freq} THz')
