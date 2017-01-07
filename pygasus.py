import time, struct, os, fcntl, signal, datetime
import hashlib

def load_pegasus_notes(data):
    notes = []
    offset = 0
    pointer = (data[offset]) + (data[offset + 1] << 8) + (data[offset + 2] << 16)
    while pointer != 0:
        notes.append(PegasusNote(data[offset:pointer]))
        offset = pointer
        pointer = (data[offset]) + (data[offset + 1] << 8) + (data[offset + 2] << 16)
    return notes

class PegasusNote:
    _XYcoords_struct = struct.Struct('<hh')
    def __init__(self, data):
        offset = 0

        strokes = []
        
        flags = data[offset + 3]
        note_contains_content = (flags & 0b10000000) != 0
        note_closed = (flags & 0b01000000) == 0
        note_closed_by_user = (flags & 0b00100000) != 0
        assert (flags & 0b00010000) != 0
        note_side_left = (flags & 0b00001000) != 0
        note_side_right = (flags & 0b00000100) != 0
        note_already_uploaded = (flags & 0b00000010) == 0
        pen_bat_low = (flags & 0b00000001) == 0
        note_id = data[offset+4]
        note_count = data[offset+5]
        timestamp = (data[offset+6]) + (data[offset+7] << 8) + (data[offset+8] << 16) + (data[offset+9] << 24)
        #assert data[offset+10] == 0x01  #Protocol ID
        data[offset+11], data[offset+12], data[offset+13]
        offset += 14
            
        stroke = []
        while offset < len(data):
            x, y = self._XYcoords_struct.unpack(data[offset:offset+4])
            if data[offset:offset+4] == b'\x00\x00\x00\x80':
                strokes.append(stroke)
                stroke = []
            else:
                stroke.append((x, y))
                
            offset += 4
            
        self._hash = hashlib.md5(data[14:]).hexdigest()
        self._strokes = strokes
        self._note_id = note_id
        
    @property
    def hash(self):
        return self._hash
    
    @property
    def note_id(self):
        return self._note_id
        
    def as_svg(self, page_width=744.09, page_height=1052.36, scale=3.543307/50):
        stroke_counter = 0
        svg = """<svg version="1.1" baseProfile="full" xmlns="http://www.w3.org/2000/svg" width="{0}" height="{1}" xml:space="preserve" xmlns:Anoto="http://www.anoto.com/dtd/20011023.dtd" Anoto:version="2.1"><g id="strokes" style="fill:none; stroke:#000000;"><Anoto:Activate PageAddress="43.0.4.01" PageTitle=""/>""".format(page_width, page_height)
        for stroke in self._strokes:
            stroke_text = []
            for pos_id, pos in enumerate(stroke):
                action = {True: 'M', False: 'L'}[pos_id == 0]
                stroke_text.append('{} {} {}'.format(action, page_width/2+pos[0]*scale, pos[1]*scale))
            svg += '<path id = "stroke{}" style="stroke:#000000; stroke-width: 1.0" d="{}" />'.format(stroke_counter, ' '.join(stroke_text))
            stroke_counter += 1            
        svg += """</g></svg>"""
        return svg
    
            

class PegasusFile:
    def __init__(self, f):
        self._data = open(f, 'rb').read()
        self._device_id = int(f.split('-')[1].split('.')[0], 16)
        
    @property
    def notes_count(self):
        return len(load_pegasus_notes(self._data))
        
    @property
    def device_id(self):
        return self._device_id
    
    def print_info(self):
        print('Data from device Id: {:012X}'.format(self.device_id))
        print('Notes count: {:02d}'.format(self.notes_count))
        
    def download_data(self):
        return self._data
    
class PegasusDevice:
    _version_struct = struct.Struct('>BBBHHHBB')
    
    def __init__(self, rawdev):
        self._f = open(rawdev, 'wb+', 0)
        
        self._product_id = None
        self._version = None
        self._pad_version = None
        self._mode = None
        self._device_id = None
        
    @property
    def device_id(self):
        if self._device_id is None:
            self._device_id = self._get_device_id()
        return self._device_id
    
    @property
    def product_id(self):
        if self._product_id is None:
            self._get_version()
        return self._product_id
    
    @property
    def version(self):
        if self._version is None:
            self._get_version()
        return self._version
    
    @property
    def pad_version(self):
        if self._pad_version is None:
            self._get_version()
        return self._pad_version
    
    @property
    def mode(self):
        if self._mode is None:
            self._get_version()
        return self._mode
    
    @property
    def mode_str(self):
        return {0x00: 'RAW', 0x01: 'XY', 0x02: 'Tablet', 0x03: 'Mobile',}.get(self.mode, 'Unknown')
        
    def print_info(self):
        print("Product ID: {}\nVersion: {}\nPad version: {}\nMode: {} ({})".format(self.product_id, self.version, self.pad_version, self.mode, self.mode_str))
        print('Device Id: {:012X}'.format(self.device_id))
        print("Notes count: {:02d}".format(self.notes_count))
        
        
    def download_data(self):
        self._dev_write_command([0xb5])
        reply = self._dev_read()
        assert reply[0] == 0xaa
        assert reply[1] == 0xaa
        assert reply[2] == 0xaa
        assert reply[3] == 0xaa
        assert reply[4] == 0xaa
        assert reply[7] == 0x55
        assert reply[8] == 0x55
        
        number_of_packets = (reply[5] << 8) + reply[6]
        
        packets = {}
        self._dev_write_command([0xb6])
        while len(packets) < number_of_packets:
            reply = self._dev_read()
            if reply is None:
                break
            packet_id = (reply[0] << 8) + reply[1]
            packets[packet_id] = reply[2:]
            
        assert len(packets) == number_of_packets
        self._dev_write_command([0xb6])
        
        data = []
        for i in range(number_of_packets):
            data.append(packets[i+1])
        return b''.join(data)
        
        
    @property
    def notes_count(self):
        self._dev_write_command([0x80, 0xc0])
        reply = self._dev_read()
        assert reply[0] == 0x81
        assert reply[1] == 0xc0
        return reply[2] + (reply[3] << 8)

        
    #Communication with device
    def _get_version(self):
        self._dev_write_command([0x95, 0x95])
        message = self._dev_read()
        b0, b1, product_id, version1, version2, pad_version, b9, mode = self._version_struct.unpack_from(message)
        
        assert b0 == 0x80
        assert b1 == 0xa9
        assert b9 == 0x0e
        assert version1 == version2
        self._product_id = product_id
        self._version = version1
        self._pad_version = pad_version
        self._mode = mode
    
    def _get_device_id(self):
        self._dev_write_command([0x80, 0xd3])
        device_id_reply = self._dev_read()
        assert device_id_reply[0] == 0x81
        assert device_id_reply[1] == 0xd3
        
        device_id = 0
        for i in range(12):
            device_id = (device_id << 8) + device_id_reply[i+2]
            
        return device_id
        
    #Raw input/output
    def _dev_write_command(self, command):
        command = bytes([0x02, len(command)]+list(command) + [0] * (6 - len(command)))
        self._f.write(command)
        
    @staticmethod
    def _ignore_signal(signum, frame):
        pass
        
    def _dev_read(self, timeout=2):
        #FIXME: handle timeout!
        ts = time.time()
        reply = b''
        signal.alarm(timeout)
        signal.signal(signal.SIGALRM, self._ignore_signal)
        while len(reply) < 64 and time.time() - ts <= timeout:
            try:
                d = self._f.read(64-len(reply))
            except InterruptedError:
                break
            if d is None:
                time.sleep(0.01)
            reply += d
        
        signal.alarm(0)
        if len(reply) == 0:
            return None
        assert len(reply) == 64
        return reply
    

    
        
        
if __name__ == '__main__':
    import argparse, stat
    
    parser = argparse.ArgumentParser(description='Communicate with pegasus devices')
    parser.add_argument('-i', '--info', action='store_true', help="Print device information")
    parser.add_argument('-d', '--device', help="Print device information", default="/dev/irisnotes")
    parser.add_argument('-n', '--no-download', help="Do not download notes", action="store_true")
    parser.add_argument('-o', '--output', help="Output directory", default="output")

    args = parser.parse_args()
    
    if stat.S_ISCHR(os.stat(args.device).st_mode):
        device = PegasusDevice(args.device)
    else:
        device = PegasusFile(args.device)
        
    if args.info:
        device.print_info()
        
    if not args.no_download:
        data = device.download_data()
        if isinstance(device, PegasusDevice):
            open(os.path.join(args.output, datetime.datetime.now().strftime('%Y%m%d%H%M%S-{:012X}.bin'.format(device.device_id))), 'wb').write(data)
        
        existing_hashes = [x.split('.')[0].split('-')[2] for x in os.listdir(args.output) if x.endswith('.svg')]
        notes = load_pegasus_notes(data)
        for note in notes:
            if note.hash in existing_hashes:
                continue
            open(os.path.join(args.output, datetime.datetime.now().strftime('%Y%m%d-{:02d}-{}.svg'.format(note.note_id, note.hash))), 'w').write(note.as_svg())
        
#data = d.download_data()
#open('data.bin', 'wb').write(data)
#print(time.time() - ts)
