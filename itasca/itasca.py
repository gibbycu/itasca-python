"""
Python connectivity for Itasca software.

This library implements a connection via sockets between Python and
the numerical modeling software from Itasca Consulting
Group.

itascacg.com/software

FLAC, FLAC3D, PFC2D, PFC3D, UDEC & 3DEC
"""

import struct
import socket
import subprocess
import numpy as np

class ItascaFishSocketServer(object):
    "handles the low level details of the socket communication"
    def __init__(self, fish_socket_id=0):
        assert type(fish_socket_id) is int and 0 <= fish_socket_id < 6
        self.port = 3333 + fish_socket_id

    def start(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind(("", self.port))
        self.socket.listen(1)
        self.conn, addr = self.socket.accept()
        print 'socket connection established by', addr

    def send_data(self, value):
        """
        Send value to Itasca software. value must be int, float,
        length two list of doubles, length three list of doubles or a
        string.
        """
        if type(value) == int:
            self.conn.sendall(struct.pack("i", 1))
            self.conn.sendall(struct.pack("i", value))
        elif type(value) == float:
            self.conn.sendall(struct.pack("i", 2))
            self.conn.sendall(struct.pack("d", value))
        elif type(value) == list and len(value)==2:
            float_list = [float(x) for x in value]
            self.conn.sendall(struct.pack("i", 5))
            self.conn.sendall(struct.pack("dd", float_list[0], float_list[1]))
        elif type(value) == list and len(value)==3:
            float_list = [float(x) for x in value]
            self.conn.sendall(struct.pack("i", 6))
            self.conn.sendall(struct.pack("ddd", float_list[0],
                                          float_list[1], float_list[2]))
        elif type(value) == str:
            length = len(value)
            self.conn.sendall(struct.pack("ii", 3, length))
            buffer_length = 4*(1+(length-1)/4)
            format_string = "%is" % buffer_length
            value += " "*(buffer_length - length)
            self.conn.sendall(struct.pack(format_string, value))
        else:
            raise Exception("unknown type in send_data")

    def read_type(self, type_string):
        byte_count = struct.calcsize(type_string)
        bytes_read = 0
        data = ''
        while bytes_read < byte_count:
            data_in = self.conn.recv(byte_count - bytes_read)
            data += data_in
            bytes_read += len(data)
        assert len(data)==byte_count, "bad packet data"
        return data

    def read_data(self):
        raw_data = self.read_type("i")
        type_code, = struct.unpack("i", raw_data)
        if type_code == 1:     # int
            raw_data = self.read_type("i")
            value, = struct.unpack("i", raw_data)
            return value
        elif type_code == 2:   # float
            raw_data = self.read_type("d")
            value, = struct.unpack("d", raw_data)
            return value
        elif type_code == 3:   # string
            length_data = self.read_type("i")
            length, = struct.unpack("i", length_data)
            buffer_length = (4*(1+(length-1)/4))
            format_string = "%is" % buffer_length
            data = self.read_type(format_string)
            return data [:length]
        elif type_code == 5:   # V2
            raw_data = self.read_type("dd")
            value0, value1 = struct.unpack("dd", raw_data)
            return [value0, value1]
        elif type_code == 6:   # V3
            raw_data = self.read_type("ddd")
            value0, value1, value3 = struct.unpack("ddd", raw_data)
            return [value0, value1, value3]
        assert False, "Data read type error"

    def get_handshake(self):
        raw_data = self.read_type("i")
        value, = struct.unpack("i", raw_data)
        print "handshake got: ", value
        return value

    def close(self):
        self.conn.close()


class ItascaSoftwareConnection(object):
    """
    Interface communication via FISH socket IO with an Itasca
    program. This class spawns a new instance of the Itasca software
    and initializes the socket communication.
    """
    def __init__(self, fish_socket_id=0):
        self.server = ItascaFishSocketServer(fish_socket_id)
        self.iteration = 0
        self.global_time = 0
        self.fishcode = 178278912

    def start(self, datafile_name):
        """
        launch Itasca software in a separate process with the given
        filename as a command line argument
        """
        args = [self.execuitable_name(), datafile_name]
        self.process = subprocess.Popen(args)

    def connect(self):
        """
        Connect to Itasca software, read fishcode to confirm connection
        """
        assert self.process
        self.server.start()
        value = self.server.get_handshake()
        print "got handshake packet"
        assert value == self.fishcode
        print "connection OK"

    def send(self, data):
        self.server.send_data(data)

    def receive(self):
        return self.server.read_data()

    def end(self):
        self.server.close()

    def executable_name(self):
        raise NotImplementedError, "derived class must implement this function"

class FLAC3D_Connection(ItascaSoftwareConnection):
    def execuitable_name(self):
        return "C:\\Program Files\\Itasca\\Flac3d500\\exe64\\flac3d500_gui_64.exe"

class PFC3D_Connection(ItascaSoftwareConnection):
    def execuitable_name(self):
        return "C:\\Program Files\\Itasca\\PFC3D400\\exe64\\evpfc3d_64.exe"

class FLAC_Connection(ItascaSoftwareConnection):
    def start(self, _=None):
        raise NotImplemented("FLAC must be started manually")
    def connect(self):
        self.process=True
        ItascaSoftwareConnection.connect(self)

class UDEC_Connection(ItascaSoftwareConnection):
    def start(self, _=None):
        raise NotImplemented("UDEC must be started manually")
    def connect(self):
        self.process=True
        ItascaSoftwareConnection.connect(self)


class FishBinaryReader(object):
    """Read structured FISH binary files.

    Call the constructor with the structured FISH filename and call
    read() to read individual values. This class also supports
    iteration. Return values are converted to python types. Supports
    int, float, string, bool, v2 and v3.

    >>> fish_file = FishBinaryReader('my_fish_data.fish')
    >>> for val in fish_file:
    ...    print val
    42
    "this is a string"
    [1.0,2.0,3.0]

    """
    def __init__(self, filename):
        self.file = open(filename, "rb")
        fishcode = self._read_int()
        assert fishcode == 178278912, "invalid FISH binary file"

    def _read_int(self):
        data = self.file.read(struct.calcsize('i'))
        value, = struct.unpack("i", data)
        return value

    def _read_double(self):
        data = self.file.read(struct.calcsize('d'))
        value, = struct.unpack("d", data)
        return value

    def read(self):
        """read and return a value (converted to a python type) from the
        .fish binary file."""
        type_code = self._read_int()

        if type_code == 1:  # int
            return self._read_int()
        if type_code == 8:  # bool
            value = self._read_int()
            return_value = True if value else False
            return return_value
        if type_code == 2:  # float
            return self._read_double()
        if type_code == 3:
            length = self._read_int()
            buffer_length = 4*(1+(length-1)/4)
            format_string = "%is" % buffer_length
            data = self.file.read(struct.calcsize(format_string))
            return data [:length]
        if type_code == 5:  # v2
            return [self._read_double(), self._read_double()]
        if type_code == 6:  # v3
            return [self._read_double(), self._read_double(),
                    self._read_double()]

    def __iter__(self):
        self.file.seek(0)  # return to the begining of the file
        self._read_int()   # pop the magic number off
        return self

    def next(self):
        try:
            return self.read()
        except:
            raise StopIteration

    def aslist(self):
        """ Return fish file contents as a Python list """
        return [x for x in self]

    def asarray(self):
        """ Return fish file contents as a numpy array.
        Types must be homogeneous."""
        return np.array(self.aslist())
