###
# SET MIN MAX FREQUENCIES IN MHZ
###
import numpy as np
import time
import EODMR_Si29 as eodmr  # Import the user-provided script as a Python module (must be on PYTHONPATH or same folder).
import pylabnet.hardware.awg.zi_hdawg as zi_hdawg
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import textwrap
from pylabnet.utils.helper_methods import load_config
from pylabnet.hardware.counter.swabian_instruments import time_tagger
import timetagger as TT


def get_marker_buffer(x: int, base: int = 16) -> int:  # Helper: round sample counts up to a multiple of 16 (HDAWG-friendly).
    return base - np.mod(float(x),float(base))  # Compute the smallest multiple of base >= x and return as int.

def upload_sequence(program: str, awgModule, to_compile=True):

        print("Uploading to HDAWG...")
        awgModule.set("compiler/sourcestring", textwrap.dedent("\n".join(program)))

        if(not to_compile): return

        # While uploading
        while awgModule.getInt('compiler/status') == -1:
            print("Waiting for HDAWG compiler...")
            time.sleep(1)

        status = awgModule.getInt('compiler/status')
        # Compilation failed
        if status == 1:
            print("Compilation failed: {awgModule.getString('compiler/statusstring')}")
            return
        # No warnings
        elif status == 0:
            print("Compilation successful with no warnings, will upload the program to the instrument.")
        # Warnings
        elif status == 2:
            print("Compilation successful with warnings, will upload the program to the instrument.")
            print(f"Compiler warning: {awgModule.getString('compiler/statusstring')}")
        else:
            print(f"Unknown status. Compiler warning: {awgModule.getString('compiler/statusstring')}")

        # Wait for the waveform upload to finish
        while (awgModule.getDouble('progress') < 1.0) and (awgModule.getInt('elf/status') != 1):
            print(f"Progress: {awgModule.getDouble('progress'):.2f}")
            time.sleep(0.2)

        elf_status = awgModule.getInt('elf/status')
        if elf_status == 0:
            print("Upload to HDAWG successful.")
        elif elf_status == 1:
            print("Upload to HDAWG failed.")


#pulse_var_dict = load_config('pulse_vars')
#dio_dict = load_config('dio_assignment_global')
class ODMR:
    def __init__(self, f_start, f_stop, f_pts, t, amp, repeat_per_freq, dio_assignments_file):
            
        self.dio_dict = load_config(dio_assignments_file)
        self.fstart = f_start
        self.fstop = f_stop
        self.pts = f_pts
        self.finc = float((f_stop-f_start)/f_pts)
        self.pulse_len = t
        self.sweep_amp = amp
        self.repeat_per_freq = repeat_per_freq

        #Readout and Ionization Parameters
        self.TSA_pulse_len = 300000 / 6
        self.green_pulse_len = 250000
        self.ionization_threshold = 100

    def sequence(self):

        plugin = f"""
        const OFF = 0;
        const TISA = 1 << {self.dio_dict['DIO_TISA_AOM']}; 
        const MW_IQ_PATH_SWITCH = 1 << {self.dio_dict['DIO_MW_PATH_SW']};
        const MW_OUTPUT_SWITCH = 1 << {self.dio_dict['DIO_MW_OUTPUT_SW']};
        const MW_IQ_OUTPUT = MW_IQ_PATH_SWITCH | MW_OUTPUT_SWITCH;
        const GREEN = 1 << {self.dio_dict['DIO_GREEN']};

        var start_freq = {int(self.fstart/self.finc)};
        var stop_freq = {int(self.fstop/self.finc)};
        var freq_step = {1};

        const t_green = {self.green_pulse_len};
        const t_read = {self.TSA_pulse_len};
        const sweep_len = {int(self.pulse_len)};
        const marker_buffer = {get_marker_buffer(self.pulse_len)};
        const sweep_amp = {self.sweep_amp};
        const repeat_per_freq = {self.repeat_per_freq};
        const ionized_trsh = {self.ionization_threshold};

        """

        constant = """

        var el_perro_verde = 0;

        wave sweep_pulse = sweep_amp * gauss(sweep_len, 1.0, sweep_len/2, sweep_len/6);
        wave sweep_marker = join(marker(marker_buffer, 1),  marker(sweep_len, 1));

        void READOUT() {
            setTrigger(0b1);
            setDIO(TISA);
            wait(t_read);
            setDIO(OFF);
            setTrigger(0b0);
        }

        void INITIALIZE() {
            setDIO(TISA);
            wait(t_read);
            setDIO(OFF);
        }

        repeat (repeat_per_freq){

            for (var i = start_freq; i <= stop_freq; i = i + freq_step) {

                if (el_perro_verde > ionized_trsh) {
                    setDIO(GREEN);
                    wait(t_green);
                    setDIO(OFF);
                    wait(t_green);
                    el_perro_verde = 0;
                }
                
                INITIALIZE();

                // Prepare ODMR frequencies
                playZero(128);
                setInt('sines/0/oscselect', 2);
                setInt('sines/1/oscselect', 2);
                setInt('sines/0/harmonic', i);
                setInt('sines/1/harmonic', i);

                setDIO(MW_IQ_OUTPUT);
                wait(50);
                playWave(1, sweep_pulse, 2, sweep_pulse, 3, 0*sweep_pulse, 4, 0*sweep_pulse + sweep_marker);
                waitWave();
                setDIO(OFF);
                wait(20);

                // Return to normal harmonic
                playZero(128);
                setInt('sines/0/harmonic', 1);
                setInt('sines/1/harmonic', 1);
                
                READOUT();

                el_perro_verde += 1;
            }
        }

        """
        return str(plugin + constant)

    def configure(self, program: str):

        self.HDAWG = zi_hdawg.Driver('dev8823', "USB", None)  # Create the driver object 
        self.awgModule = self.HDAWG.daq.awgModule()  # Create an AWG module object (compiler + uploader). 
        self.awgModule.set("device", 'dev8823')  # Point the AWG module at the correct hardware device id. 
        self.awgModule.set("index", 0)  # Select which AWG core we are programming. 
        self.awgModule.execute()  # Start the AWG module so it can accept compiler/uploader commands. 
        
        self.sample_freq = 0 #define as an int n such that (2.4GHz)/2^n to get sampling frequecy (293kHz when n=13)
        self.HDAWG.setd("system/clocks/sampleclock/freq", 2.4e9/(2^int(self.sample_freq))) #set sample frequency 
        self.fs_hz = float(self.HDAWG.getd("system/clocks/sampleclock/freq"))  # Read the active sample clock frequency in Hz from the device. 


        self.HDAWG.seti("system/awg/channelgrouping", 0)  # 4x2 grouping
        self.HDAWG.seti(f"awgs/0/single", 1)  # Put the AWG core into single-shot mode so it stops when the program ends.
        self.HDAWG.seti(f"sigouts/0/on", 1)  # Enable the physical analog output channel.
        self.HDAWG.seti(f"sigouts/1/on", 1)  # Enable the physical analog output channel.
        
        # set stepping frequency
        self.HDAWG.setd('oscs/2/freq', self.finc)

        # set DIO in AWG-controlled  mode
        self.HDAWG.seti('dios/0/mode', 1)

        # set oscillators in non-AWG-controlled mode
        self.HDAWG.seti('system/awg/oscillatorcontrol', 0)

        # set right waveform modulation mode
        self.HDAWG.seti('awgs/0/outputs/0/modulation/mode', 1)
        self.HDAWG.seti('awgs/0/outputs/1/modulation/mode', 2)

        # set IQ params (amps)
        amp_I = self.HDAWG.getd('sines/0/amplitudes/0')
        self.HDAWG.setd('awgs/0/outputs/0/gains/0', amp_I/0.8)

        amp_Q = self.HDAWG.getd('sines/1/amplitudes/1')
        self.HDAWG.setd('awgs/0/outputs/1/gains/1', amp_Q/0.8)

        # Logic counter settings
        self.HDAWG.seti('cnts/0/enable', 1)
        self.HDAWG.seti('cnts/0/mode', 3)
        self.HDAWG.seti('cnts/0/inputselect', 32)
        self.HDAWG.seti('cnts/0/gateselect', 32)
        
        self.HDAWG.seti(f"awgs/0/enable", 0)  # hard-disable AWG core before upload

        upload_sequence(program, self.awgModule)

        # Initialize counters
        ctr = time_tagger.Wrap(TT.createTimeTagger())
        ctr.start_gated_counter(
            name='gated_1', 
            click_ch=1, #input channel of TT for counts from SNSPD
            gate_ch=3, #input channel of TT for gate from DIO port of HDAWG
            bins=self.pts*self.repeat_per_freq
        )
    #

    def launch(self):

        self.HDAWG.seti('awgs/0/enable', 1)
        t0 = time.time()  # Record start time for timeout tracking.
        while self.HDAWG.geti(f"awgs/{self.awg_index}/enable") == 1:  # Poll until the AWG core disables itself.
            if (time.time() - t0) > 30.0:  # Check for timeout condition.
                raise TimeoutError("Timed out waiting for AWG to finish.")  # Raise if AWG did not stop in time.
            time.sleep(0.01)  # Sleep briefly between polls to reduce CPU load.

        # Ensures we only pull from the time tagger once per sweep
        self.measurement = time_tagger.get_counts(name='gated_1')
        return self.measurement
    

    def avg_counts(self, frequency):
        # Current frequency step index
        i = int((frequency/self.finc))
        return np.mean([val for idx, val in enumerate(self.measurement) if idx-i % self.repeat_per_freq == 0])
