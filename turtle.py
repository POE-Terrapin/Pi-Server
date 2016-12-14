import serial
import logging
import time
import threading

STOP, GO_FORWARD, TURN_LEFT, TURN_RIGHT = range(4)

data_labels = ['ls_f', 'ls_b', 'ir_f', 'ir_r', 'ir_l', 'ts', 'sm', 'bh', 'gx', 'gy', 'gz']

class Logger(object):
    """ Wrapper Class to Instantiate logger with supplied parameters """
    def __init__(self, name, level='info'):

        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        self.logger.setLevel(getattr(logging, level.upper()))
        self.formatter = logging.Formatter(
            (
                '[%(asctime)s] %(message)s'
            )
        )

        self.file = time.strftime("%G-%m-%d-%H:%M:%S.csv") # Time-Stamped Log File

        # Write Header
        with open(self.file, 'a') as f:
            f.write('[time] [' + ', '.join(data_labels)+']\n')

        self.ch = logging.FileHandler(self.file)
        self.ch.setFormatter(self.formatter)
        self.logger.addHandler(self.ch)

    def log(self, data, level='info'):
        func = getattr(self.logger, level)
        func(str(data))

class Turtle(object):
    """ Creates the overarching Turtle class, which controlls the turtle """

    def __init__(self, port='/dev/ttyACM0', baud=9600):
        """ Imports serial and creates the arduino """

        self.port = port
        self.serial = serial.Serial(port, baud) # serial: arduinoSerialData, check port number

        self.logger = Logger('turtle-logger')
         
        # Initialize all the sensors
        self.LS = {'front':0, 'back':0} # Light sensor dictionary
        self.IR = {'front':0, 'right':0, 'left':0} # IR sensor dictionary
        self.TS = 0 # Temperature sensor
        self.SM = 0 # Soil moisture sensor
        self.behavior = STOP
        self.GX = self.GY = self.GZ = 0

        # Set up limits to look for (filler values)
        self.distanceLimit = 100 # limit before something is 'seen' in that direction
        self.seeLight = 100
        self.heatLimit = 30 # if temperature sensor is above this value, look for shade
        self.moistureLimit = 100 # if moisture is too low, change eye color
        
        # Set up decision points to control behavior
        self.seekShade = False
        self.inLight = 0 # 0 indicates fully in light, 1 is front only, 2 is back only, 3 is full shade
        self.lastLightUpdate = time.time() # record the time spent in light every minute
        self.minuteLightAverage = 0 # averages the light received over a minute
        self.timeSpentInLight = 0 # keeps track of how long we've been in the light 
        self.HLQ = {'day':60, 'night':0, 'met':False} # if it is daytime, try to get light for 8 hours. If night, no light needed
        self.timeStarted = time.time() # will let us figure out if it is day or night
        self.currentHour = 0

        self.status = [0 for _ in range(len(data_labels))]

    def getFirstRead(self):
        """ Gets the first read and sets that as calibration things """
        while True:
            if(self.serial.inWaiting()>0):
                dataRead = self.serial.readline()
                dataList = dataRead.split(',')
                if dataList[0] != '' and len(dataList) == len(data_labels):
                        for index in range(len(dataList)):
                            dataList[index] = float(dataList[index])
                        # Set up calibration for what is defined as shade vs light
                        self.seeLight = (dataList[0]+dataList[1])/2 - 100
                    
                        # Calibrate what is defined as near. Average the readings of all 3 sensors and add 100.
                        self.distanceLimit = (dataList[2]+dataList[3]+dataList[4])/3 +100
                        print(self.seeLight, self.distanceLimit)
                        break
        
    def run(self, lock):
        """ Loop that runs the decision algorithm """
        while self.serial._isOpen:
            if(self.serial.inWaiting()>0):
                dataRead = self.serial.readline()
                dataList = dataRead.split(',')
                if dataList[0] != '' and len(dataList) == len(data_labels): # makes sure it is the full set of data to read
                    self.assignData(dataList)
                    self.update_status(lock)
                    self.logData()

                    # Check to see if we need to go to shade
                    enoughLight = self.checkHourlyLight()
                    tooHot = self.TS > self.heatLimit

                    if enoughLight or tooHot:
                        self.seekShade = True
                    else:
                        self.seekShade = False

                    if self.seekShade:
                        direction = self.goToShade()
                    else:
                        direction = self.goToLight()
                    
                    if self.SM < self.moistureLimit:
                        eyesYellow = True
                    else:
                        eyesYellow = False
                    #print('--->')    
                    #print(direction)
                    if eyesYellow:
                        direction += 4 # Adds 4 so that the arduino knows to turn the eyes yellow
                    self.serial.write(str(direction))
                                       
                else:
                    #print(dataRead)
                    pass
            time.sleep(0.05)

    def assignData(self, dataList):
        """ Assigns the data to the proper variables and converts it to floats.
            Data is received as: 'FLS,BLS,FIR,RIR,LIR,TS,SM'. """
        for index in range(len(dataList)):
            try:
                dataList[index] = float(dataList[index])
            except ValueError:
                print dataList
                print dataList[index]

        self.LS['front'], self.LS['back'] = dataList[0], dataList[1]
        self.IR['front'], self.IR['right'], self.IR['left'] = dataList[2], dataList[3], dataList[4]
        self.TS = dataList[5]
        self.SM = dataList[6]
        self.behavior = dataList[7]

        self.GX = dataList[8]
        self.GY = dataList[9]
        self.GZ = dataList[10]

    def checkInLight(self):
        """ Checks if the turtle is in light.
            0 means fully in light, 1 means the back is in shadow,
            2 means the front is in shadow and the back isn't,
            3 means fully in shadow. """
        if self.LS['front'] >= self.seeLight and self.LS['back'] >= self.seeLight:
            self.inLight = 0
        elif self.LS['front'] >= self.seeLight and self.LS['back'] < self.seeLight:
            self.inLight = 1
        elif self.LS['front'] < self.seeLight and self.LS['back'] >= self.seeLight:
            self.inLight = 2
        else:
            self.inLight = 3
        
    def checkHourlyLight(self):
        """ Checks to see how much light has been received in the hour.
            Returns True if the quota has been met, False if it has not. """
        # Check if it has been an hour since currentHour was last updated
        hourCheck = int((self.timeStarted - time.time())/3600)
        if hourCheck != self.currentHour:
            # if it has been an hour since these were zeroed out, zero 'em off
           self.minuteLightAverage = 0
           self.self.lastLightUpdated = time.time()
           self.timeSpentInLight = 0
           self.HLQ['met'] = False
           self.currentHour = hourCheck

        self.checkInLight()

        # add different amounts depending on how much light the turtle is in
        if self.inLight == 0:
            self.minuteLightAverage += 1
        elif self.inLight == 1 or self.inLight == 2:
            self.minuteLightAverage += .5
        else:
            self.minuteLightAverage += 0

        # If it has been a minute since the last average was taken, take it
        if(self.lastLightUpdate - time.time()) >= 60: # if it has been 1 minute, update the timeSpentInLight
            self.timeSpentInLight += self.minuteLightAverage/600 # assuming ten checks per second
            self.minuteLightAverage = 0
            self.lastLightUpdate = time.time()

        if self.currentHour < 8:
            lightQuota = self.HLQ['day']
        else:
            lightQuota = self.HLQ['night']

        if lightQuota < self.timeSpentInLight:
            self.HLQ['met'] = True
            
        return self.HLQ['met']

    def goToShade(self):
        """ Travels to the shade and stops if fully in shade.
            Returns forward (0), right (1), left (2), or stop (3) """
        if self.inLight == 3: # stop if in shade
            return STOP
        elif self.inLight == 1: # try to turn around if there is shade behind
            return TURN_RIGHT
        else:
            return self.checkForward()
        
    def goToLight(self):
        """ Wanders around in the light, turns if it gets into shade. """
        if self.inLight == 2:
            # turn if the front IR gets into the shade
            return self.checkTurns()
        else:
            # otherwise, go wherever
            return self.checkForward()
        
    def checkForward(self):
        """ Checks to see which way it can go and returns
            forward (0), right (1), or left (2) """
        if self.IR['front'] < self.distanceLimit:
            return GO_FORWARD 
        else: # check which direction we should turn
            return self.checkTurns()
        
    def checkTurns(self):
        """ Checks which turn it should make. Returns right (1) or left (2) """
        if self.IR['right'] < self.distanceLimit and (self.IR['right'] - self.IR['left']) < 25:
            # checks to see if there is anything to the right. If there is not,
            #  and there is nothing significantly closer to the right than the left,
            #  the turtle turns right
            return TURN_RIGHT
        else:
            # goes left if it can't go forward or right. Maybe change later?
            return TURN_LEFT

    def update_status(self, lock):
        with lock:
            #print 'got lock2!'
            self.status = [self.LS['front'], self.LS['back'], self.IR['front'], self.IR['right'], self.IR['left'], self.TS, self.SM, self.behavior, self.GX, self.GY, self.GZ]

    def logData(self):
        """ Logs the data into a csv file """
        self.logger.log(self.status)
