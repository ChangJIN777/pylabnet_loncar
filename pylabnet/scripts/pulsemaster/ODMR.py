###
# SET MIN MAX FREQUENCIES IN GHZ AND PULSE TIME IN NS
###

import numpy as np
import time
import pylabnet.hardware.awg.zi_hdawg as zi_hdawg
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import textwrap
from pylabnet.utils.helper_methods import load_config
from pylabnet.hardware.counter.swabian_instruments import time_tagger
import TimeTagger as TT


dio_dict = load_config("C:\\Users\\User\\Documents\\pylabnet_loncar\\pylabnet\\configs\\channel assignments\\dio_assignment_hdawg2")
var_dict = load_config("C:\\Users\\User\\Documents\\pylabnet_loncar\\pylabnet\\configs\\channel assignments\\pulse_vars")


def get_marker_buffer(x: int, base: int = 16) -> int:  # Helper: round sample counts up to a multiple of 16 (HDAWG-friendly).
    return base - int(np.mod(float(x), float(base)))  # Compute the smallest multiple of base >= x and return as int.


def time_to_samples(t_s: float, samp_rate: float):
    return int(round(t_s * samp_rate))


def upload_sequence(dataset, program, awgModule, to_compile=True):

    dataset.log.info(f"Uploading to HDAWG...")
    awgModule.set("compiler/sourcestring", textwrap.dedent(program))

    if (not to_compile):
        return

    # While uploading
    while awgModule.getInt('compiler/status') == -1:
        dataset.log.info(f"Waiting for HDAWG compiler...")
        time.sleep(1)

    status = awgModule.getInt('compiler/status')
    # Compilation failed
    if status == 1:
        dataset.log.warn(f"Compilation failed: {awgModule.getString('compiler/statusstring')}")
        return
    # No warnings
    elif status == 0:
        dataset.log.info(f"Compilation successful with no warnings, will upload the program to the instrument.")
    # Warnings
    elif status == 2:
        dataset.log.warn(f"Compilation successful with warnings, will upload the program to the instrument.")
        dataset.log.warn(f"Compiler warning: {awgModule.getString('compiler/statusstring')}")
    else:
        dataset.log.warn(f"Unknown status. Compiler warning: {awgModule.getString('compiler/statusstring')}")

    # Wait for the waveform upload to finish
    while (awgModule.getDouble('progress') < 1.0) and (awgModule.getInt('elf/status') != 1):
        dataset.log.info(f"Progress: {awgModule.getDouble('progress'):.2f}")
        time.sleep(0.2)

    elf_status = awgModule.getInt('elf/status')
    if elf_status == 0:
        dataset.log.info(f"Upload to HDAWG successful.")
    elif elf_status == 1:
        dataset.log.warn(f"Upload to HDAWG failed.")


class MyPopup(QWidget):
    def __init__(self, parent=None):
        QWidget.__init__(self)
        self.gridLayout = QGridLayout(self)
        self.setLayout(self.gridLayout)
        self.setWindowTitle("ODMR parameters")
        self.parent = parent

        self.btn1 = QPushButton("Push parameters", self)
        self.label1 = QLabel("Frequency sweep start (GHz):", self)
        self.label2 = QLabel("Frequency sweep end (GHz):", self)
        self.label3 = QLabel("Frequency sweep number of points:", self)
        self.label4 = QLabel("Pulse duration (ns):", self)
        self.label5 = QLabel("Sweep pulse amplitude (0 to 1):", self)
        self.label6 = QLabel("Threshold (counts):", self)
        self.label7 = QLabel("Repeat per frequency:", self)

        #default gui values?
        self.textfield1 = QLineEdit(str(var_dict["start_freq"]), self)
        self.textfield2 = QLineEdit(str(var_dict["end_freq"]), self)
        self.textfield3 = QLineEdit(str(var_dict["num_pts"]), self)
        self.textfield4 = QLineEdit(str(var_dict["pulse_len"]), self)
        self.textfield5 = QLineEdit('1', self)
        self.textfield6 = QLineEdit('5', self)
        self.textfield7 = QLineEdit('10', self)

        self.gridLayout.addWidget(self.label1, 0, 0)
        self.gridLayout.addWidget(self.label2, 1, 0)
        self.gridLayout.addWidget(self.label3, 2, 0)
        self.gridLayout.addWidget(self.label4, 3, 0)
        self.gridLayout.addWidget(self.label5, 4, 0)
        self.gridLayout.addWidget(self.label6, 5, 0)
        self.gridLayout.addWidget(self.label7, 6, 0)
        self.gridLayout.addWidget(self.textfield1, 0, 1)
        self.gridLayout.addWidget(self.textfield2, 1, 1)
        self.gridLayout.addWidget(self.textfield3, 2, 1)
        self.gridLayout.addWidget(self.textfield4, 3, 1)
        self.gridLayout.addWidget(self.textfield5, 4, 1)
        self.gridLayout.addWidget(self.textfield6, 5, 1)
        self.gridLayout.addWidget(self.textfield7, 6, 1)
        self.gridLayout.addWidget(self.btn1, 7, 1)

        self.btn1.clicked.connect(self.push_parameters)

    def push_parameters(self):

        self.f1 = float(self.textfield1.text()) * 1e9
        self.f2 = float(self.textfield2.text()) * 1e9
        self.f_pts = float(self.textfield3.text())
        self.finc = float((self.f2 - self.f1) / self.f_pts)
        t = float(self.textfield4.text()) * 1e-9
        self.pulse_len = time_to_samples(t, 2.4e9)

        sweep_amp = self.textfield5.text()
        repeat_per_freq = int(self.textfield7.text())
        threshold = int(self.textfield6.text())

        #Readout and Ionization Parameters
        TSA_pulse_len = time_to_samples(float(var_dict["init_pulse_len"]) * 1e-9, 2.4e9)
        green_pulse_len = time_to_samples(float(var_dict["green_pulse_len"]) * 1e-9, 2.4e9)

        plugin = f"""
        const OFF = 0;
        const TISA = 1 << {dio_dict['DIO_TISA_AOM']};
        const MW_IQ_PATH_SWITCH = 1 << {dio_dict['DIO_MW_PATH_SW']};
        const MW_OUTPUT_SWITCH = 1 << {dio_dict['DIO_MW_OUTPUT_SW']};
        const MW_IQ_OUTPUT = MW_IQ_PATH_SWITCH | MW_OUTPUT_SWITCH;
        const GREEN = 1 << {dio_dict['DIO_GREEN']};

        var start_freq = {int(self.f1/self.finc)};
        var stop_freq = {int(self.f2/self.finc)};
        var freq_step = {1};

        const t_green = {green_pulse_len};
        const t_read = {TSA_pulse_len};
        const sweep_len = {int(self.pulse_len)};
        const marker_buffer = {get_marker_buffer(self.pulse_len)};
        const sweep_amp = {sweep_amp};
        const repeat_per_freq = {repeat_per_freq};
        const ionized_trsh = {threshold};

        """

        constant = """

        var el_perro_verde = 0;

        wave sweep_pulse = join(sweep_amp * gauss(sweep_len, 1.0, sweep_len/2, sweep_len/6), zeros(marker_buffer));
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
                playWave(1, sweep_pulse, 2, sweep_pulse+sweep_marker);
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

        self.awgModule = self.parent.HDAWG.daq.awgModule()
        self.awgModule.set("device", 'DEV8823')  # Point the AWG module at the correct hardware device id.
        self.awgModule.set('index', 0) # Core index
        self.awgModule.execute()

        upload_sequence(self.parent, plugin + constant, self.awgModule)

        self.parent.repeat_per_freq = repeat_per_freq

        # Initialize counters
        self.ctr = time_tagger.Wrap(TT.createTimeTagger())
        self.ctr.start_gated_counter(
            name='gated_1',
            click_ch=1, #input channel of TT for counts from SNSPD
            gate_ch=2, #input channel of TT for gate from DIO port of HDAWG
            bins=self.f_pts * repeat_per_freq
        )

        self.parent.FLAG = True
        self.parent.ON = False


def configure(self):
    self.HDAWG = zi_hdawg.Driver('dev8823', "1GbE", None)

    self.HDAWG.setd("system/clocks/sampleclock/freq", 2.4e9) #set sample frequency

    self.HDAWG.seti("system/awg/channelgrouping", 0)  # 4x2 grouping

    self.HDAWG.seti(f"sigouts/0/on", 1)  # Enable the physical analog output channel.
    self.HDAWG.seti(f"sigouts/1/on", 1)  # Enable the physical analog output channel.
    self.HDAWG.seti('dios/0/mode', 1)  # set DIO in AWG-controlled  mode

    self.HDAWG.setd('oscs/2/freq', self.finc) # set stepping frequency

    # set oscillators in non-AWG-controlled mode
    self.HDAWG.seti('system/awg/oscillatorcontrol', 0)

    # set right waveform modulation mode
    self.HDAWG.seti('awgs/0/outputs/0/modulation/mode', 1)
    self.HDAWG.seti('awgs/0/outputs/1/modulation/mode', 2)

    # set IQ params (amps)
    amp_I = self.HDAWG.getd('sines/0/amplitudes/0')
    self.HDAWG.setd('awgs/0/outputs/0/gains/0', amp_I)

    amp_Q = self.HDAWG.getd('sines/1/amplitudes/1')
    self.HDAWG.setd('awgs/0/outputs/1/gains/1', amp_Q)

    # Logic counter settings
    self.HDAWG.seti('cnts/0/enable', 1)
    self.HDAWG.seti('cnts/0/mode', 3)
    self.HDAWG.seti('cnts/0/inputselect', 32)
    self.HDAWG.seti('cnts/0/gateselect', 32)

    self.N_steps = self.f_pts
    self.freq_step = self.f_inc

    self.gui.w = MyPopup(parent=self)
    self.gui.w.setGeometry(QRect(2000, 400, 500, 300))
    self.gui.w.show()


def experiment(frequency, self, **kwargs):

    # Only perform the experiment on the first freq value of the sweep
    # The experiment sweeps all frequency values at once, but this function
    # is called once per frequency value; for subsequent frequency values we
    # simply just use the cached self.measurement result and return the
    # appropriate datapoints.
    if self.FLAG:
        time.sleep(0.1)
        if not self.HDAWG.geti('awgs/0/enable'):
            self.HDAWG.seti('awgs/0/enable', 1)
            self.FLAG = False
            time.sleep(0.1)
            self.ON = True
            self.measured = False

    while self.ON:
        self.ON = self.HDAWG.geti('awgs/0/enable')

    # Ensures we only pull from the time tagger once per sweep
    if not self.measured:
        self.measurement = self.ctr.get_counts(name='gated_1')
        self.measured = True

    # Current frequency step index
    i = int((frequency / self.finc))

    if frequency == self.max:
        self.FLAG = True
        self.ctr.clear_ctr(name='gated_1')

    return np.mean([val for idx, val in enumerate(self.measurement) if idx - i % self.parent.repeat_per_freq == 0])
