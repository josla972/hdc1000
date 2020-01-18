"""Support for HDC1000 temperature and humidity sensor."""
from datetime import timedelta
from functools import partial
import logging
import sys
import os
import time

import smbus  # pylint: disable=import-error
sys.path.append(os.path.dirname(__file__)) 
import SDL_Pi_HDC1000 # pylint: disable=import-error

import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
import homeassistant.helpers.config_validation as cv
from homeassistant.const import TEMP_FAHRENHEIT, CONF_NAME, CONF_MONITORED_CONDITIONS
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle
from homeassistant.util.temperature import celsius_to_fahrenheit

_LOGGER = logging.getLogger(__name__)


HDC1000_CONFIG_TEMPERATURE_RESOLUTION_14BIT = (0x0000)
HDC1000_CONFIG_TEMPERATURE_RESOLUTION_11BIT = (0x0400)

HDC1000_CONFIG_HUMIDITY_RESOLUTION_14BIT = (0x0000)
HDC1000_CONFIG_HUMIDITY_RESOLUTION_11BIT = (0x0100)
HDC1000_CONFIG_HUMIDITY_RESOLUTION_8BIT = (0x0200)

CONF_I2C_ADDRESS = "i2c_address"
CONF_I2C_BUS = "i2c_bus"
CONF_HUMIDITY_RESOLUTION = "humidity_resolution"
CONF_TEMPERATURE_RESOLUTION = "temperature_resolution"
CONF_HUMIDITY_RESOLUTION_TYPES = [8, 11, 14]
CONF_TEMPERATURE_RESOLUTION_TYPES = [11, 14]

CONF_HUMIDITY_RESOLUTION_DICT = {8:HDC1000_CONFIG_HUMIDITY_RESOLUTION_8BIT,
                                 11:HDC1000_CONFIG_HUMIDITY_RESOLUTION_11BIT,
                                 14:HDC1000_CONFIG_HUMIDITY_RESOLUTION_14BIT}

CONF_TEMPERATURE_RESOLUTION_DICT = {11:HDC1000_CONFIG_TEMPERATURE_RESOLUTION_11BIT,
                                    14:HDC1000_CONFIG_TEMPERATURE_RESOLUTION_14BIT}

DEFAULT_NAME = "HDC1000 Sensor"
DEFAULT_I2C_ADDRESS = "0x76"
DEFAULT_I2C_BUS = 1
DEFAULT_HUMIDITY_RESOLUTION = 14
DEFAULT_TEMPERATURE_RESOLUTION = 14

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=3)

SENSOR_TEMP = "temperature"
SENSOR_HUMID = "humidity"
SENSOR_TYPES = {
    SENSOR_TEMP: ["Temperature", None],
    SENSOR_HUMID: ["Humidity", "%"],
}
DEFAULT_MONITORED = [SENSOR_TEMP, SENSOR_HUMID]

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_I2C_ADDRESS, default=DEFAULT_I2C_ADDRESS): cv.string,
        vol.Optional(CONF_MONITORED_CONDITIONS, default=DEFAULT_MONITORED): vol.All(
            cv.ensure_list, [vol.In(SENSOR_TYPES)]
        ),
        vol.Optional(CONF_I2C_BUS, default=DEFAULT_I2C_BUS): vol.Coerce(int),
        vol.Optional(CONF_HUMIDITY_RESOLUTION, default=DEFAULT_HUMIDITY_RESOLUTION): vol.All(
                    vol.Coerce(int), vol.In(CONF_HUMIDITY_RESOLUTION_TYPES)),
        vol.Optional(CONF_TEMPERATURE_RESOLUTION, default=DEFAULT_TEMPERATURE_RESOLUTION): vol.All(
                    vol.Coerce(int), vol.In(CONF_TEMPERATURE_RESOLUTION_TYPES)
        )
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    SENSOR_TYPES[SENSOR_TEMP][1] = hass.config.units.temperature_unit
    name = config.get(CONF_NAME)
    i2c_address = config.get(CONF_I2C_ADDRESS)
    temperature_resolution = CONF_TEMPERATURE_RESOLUTION_DICT[config.get(CONF_TEMPERATURE_RESOLUTION)]
    humidity_resolution = CONF_HUMIDITY_RESOLUTION_DICT[config.get(CONF_HUMIDITY_RESOLUTION)]

    bus = config.get(CONF_I2C_BUS)
    sensor = await hass.async_add_job(
        partial(
            SDL_Pi_HDC1000.SDL_Pi_HDC1000,
            bus,
            i2c_address,
        )
    )

    sensor_handler = await hass.async_add_job(HDC1000Handler, sensor, temperature_resolution, humidity_resolution)

    dev = []
    try:
        for variable in config[CONF_MONITORED_CONDITIONS]:
            dev.append(
                HDC1000Sensor(sensor_handler, variable, SENSOR_TYPES[variable][1], name)
            )
    except KeyError:
        pass

    async_add_entities(dev, True)


class HDC1000Handler:
    """HDC1000 sensor working in i2C bus."""

    def __init__(self, sensor, temperature_resolution, humidity_resolution):
        """Initialize the sensor handler."""
        self.sensor = sensor
        self.sensor.turnHeaterOn() 
        time.sleep(1.0) # Burn off condensed stuff.
        self.sensor.turnHeaterOff() 
        self.update()
        # Main Program
        #print "------------"
        #print "Manfacturer ID=0x%X"% self.sensor.readManufacturerID()  
        #print "Device ID=0x%X"% self.sensor.readDeviceID()  
        #print "Serial Number ID=0x%X"% self.sensor.readSerialNumber()  
        
        # change temperature resolution
        self.sensor.setTemperatureResolution(temperature_resolution)
        self.sensor.setHumidityResolution(humidity_resolution)

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Read sensor data."""
        self.temperature = self.sensor.readTemperature()
        self.humidity = self.sensor.readHumidity()

class HDC1000Sensor(Entity):
    """Implementation of the HDC1000 sensor."""

    def __init__(self, hdc1000_client, sensor_type, temp_unit, name):
        """Initialize the sensor."""
        self.client_name = name
        self._name = SENSOR_TYPES[sensor_type][0]
        self.hdc1000_client = hdc1000_client
    #    hdc1000 = SDL_Pi_HDC1000.SDL_Pi_HDC1000(bus, i2c_address)
        self.temp_unit = temp_unit
        self.type = sensor_type
        self._state = None
        self._unit_of_measurement = SENSOR_TYPES[sensor_type][1]

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self.client_name} {self._name}"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement of the sensor."""
        return self._unit_of_measurement

    async def async_update(self):
        """Get the latest data from the HDC1000 and update the states."""
        await self.hass.async_add_job(self.hdc1000_client.update)
        if self.type == SENSOR_TEMP:
            temperature = round(self.hdc1000_client.temperature, 1)
            if self.temp_unit == TEMP_FAHRENHEIT:
                temperature = round(celsius_to_fahrenheit(temperature), 1)
            self._state = temperature
        elif self.type == SENSOR_HUMID:
            self._state = round(self.hdc1000_client.humidity, 1)


