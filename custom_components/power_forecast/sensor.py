"""The Power Forecast integration."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
from datetime import timedelta,datetime
import logging
import async_timeout

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.core import HomeAssistant, callback, HomeAssistant
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
import pytz
from scipy.signal import find_peaks
import matplotlib.pyplot as plt



from .const import DOMAIN,SAVE_PICTURES
from .apis import ForecastApi,ForecastEntry,TibberApi, ForecastSolarApi
from .helpers import bucket


_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: Callable,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    if not "apis" in config:
        raise Exception("No APIs specified")
    hasApiForWholeDay = False
    apis = []
    if("tibber" in config["apis"]):
        apis.append(TibberApi(config["apis"]["tibber"]["token"]))
        hasApiForWholeDay = True
    if("forecast_solar" in config["apis"]):
        apis.append(ForecastSolarApi(config["apis"]["forecast_solar"]["urls"], config["apis"]["forecast_solar"]["watt_threshold"], config["apis"]["forecast_solar"]["price"]))

    if not hasApiForWholeDay:
        raise Exception("Needs at least one API that covers the whole day, like Tibber")
    coordinator = DataCoordinator(hass, apis)

    entities = [
        LowestPriceEntity(coordinator),
        SortedBucketEntity(coordinator)
    ]

    if("sensors" in config):
        if("peak" in config["sensors"]):
            for sensor in config["sensors"]["peak"]:
                sensor: dict
                entities.append(
                    PricePeakEntity(coordinator, sensor["name"], sensor.get("peak_threshold", None), sensor.get("peak_distance", None), sensor.get("peak_max_width", None), sensor.get("peak_lookup_window", None), sensor.get("peak_prominence", None), sensor.get("trough", False))
                )

    await coordinator.async_config_entry_first_refresh()

    async_add_entities(entities)

class DataCoordinator(DataUpdateCoordinator):
    """My custom coordinator."""

    cacheBuilders: list[Callable[[HomeAssistant, dict[datetime, list[ForecastEntry]]], None]] = []
    apis: list[ForecastApi]

    def __init__(self, hass: HomeAssistant, apis: list[ForecastApi]):
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="Power Update",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(minutes=15),
        )
        self.apis = apis
        hass.data[DOMAIN]["lastUpdate"] = None

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        lastUpdate = self.hass.data[DOMAIN]["lastUpdate"]
        now = datetime.now(pytz.utc)
        if(lastUpdate is None or lastUpdate < now - timedelta(hours = 2)):
            forecastsByBucket: dict[datetime, list[ForecastEntry]] = dict()
            for api in self.apis:

                async with async_timeout.timeout(10):
                    forecasts = await api.getForecast()
                    for forecast in forecasts:
                        forecastBucket = forecast.startingAt
                        forecastsByBucket.setdefault(forecastBucket, [])
                        forecastsByBucket[forecastBucket].append(forecast)
            for cacheBuilder in self.cacheBuilders:
                cacheBuilder(self.hass, forecastsByBucket)
            self.hass.data[DOMAIN]["lastUpdate"] = now
        
        return bucket(now)

    def registerCacheBuilder(self, func: Callable[[HomeAssistant, dict[datetime, list[ForecastEntry]]], None]):
        self.cacheBuilders.append(func)

class SortedBucketEntity(SensorEntity):
    _attr_state_class = SensorStateClass.TOTAL
    _attr_name = "Power Forecast Sorted Price Level"
    coordinator: CoordinatorEntity

    def __init__(self, coordinator: DataCoordinator):
        """Pass coordinator to CoordinatorEntity."""
        # super().__init__(coordinator)
        coordinator.registerCacheBuilder(self.buildCache)
        self.coordinator = coordinator

    def buildCache(self, hass: HomeAssistant, forecastsByBucket: dict[datetime, list[ForecastEntry]]) -> dict[datetime, Any]:
        forecastsByDay: dict[datetime, list[ForecastEntry]] = {}
        for forecastList in forecastsByBucket.values():
            for forecast in forecastList:
                day = datetime(forecast.startingAt.year, forecast.startingAt.month, forecast.startingAt.day, tzinfo=forecast.startingAt.tzinfo)
                forecastsByDay.setdefault(day, [])
                forecastsByDay[day].append(forecast)

        bucketToLevel: dict[datetime, int] = {}
        def sortByPrice(forecast: ForecastEntry):
            return forecast.price
        for day, forecasts in forecastsByDay.items():
            forecasts.sort(key = sortByPrice)
            for i in range(len(forecasts) - 1):
                bucketToLevel[forecasts[i].startingAt] = i

        hass.data[DOMAIN]["sortedBucketEntity"] = bucketToLevel

    async def async_update(self):
        await self.coordinator.async_request_refresh()
        currentBucket = self.coordinator.data
        if currentBucket in self.coordinator.hass.data[DOMAIN]["sortedBucketEntity"]:
            self._attr_native_value = self.coordinator.hass.data[DOMAIN]["sortedBucketEntity"][currentBucket]
        else:
          self._attr_native_value = None  

class LowestPriceEntity(SensorEntity): #CoordinatorEntity

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_name = "Power Forecast Lowest Price"
    coordinator: CoordinatorEntity

    def __init__(self, coordinator: DataCoordinator):
        """Pass coordinator to CoordinatorEntity."""
        # super().__init__(coordinator)
        coordinator.registerCacheBuilder(self.buildCache)
        self.coordinator = coordinator

    # @callback
    # def _handle_coordinator_update(self) -> None:
    #     """Handle updated data from the coordinator."""
    #     self._attr_native_value = self.coordinator.hass.data[DOMAIN]["priceEntityCache"][self.coordinator.data]
    #     self.async_write_ha_state()

    def buildCache(self, hass: HomeAssistant, forecastsByBucket: dict[datetime, list[ForecastEntry]]) -> dict[datetime, Any]:
        cache: dict[datetime, float] = {}
        for bucket, forecasts in forecastsByBucket.items():
            tmpMin = None
            if(forecasts is not None):
                for forecast in forecasts:
                    if(tmpMin is None or forecast.price < tmpMin):
                        tmpMin = forecast.price
            min = -1.0
            if(tmpMin is not None):
                min = tmpMin
            cache[bucket] = min
        hass.data[DOMAIN]["priceEntityCache"] = cache

        if SAVE_PICTURES:

            def formatTime(time: datetime):
                if(time.hour % 6 == 0 and time.minute == 0):
                    return time.strftime("%c")
                else:
                    return ""
            plt.figure()
            plt.xticks(rotation=45, ha='right', ticks=list(cache.keys()), labels=list(map(formatTime, cache.keys())))
            plt.subplots_adjust(bottom=0.50)
            plt.plot(cache.keys(), cache.values())
            plt.savefig('/tmp/PriceEntity.png')

    async def async_update(self):
        await self.coordinator.async_request_refresh()
        currentBucket = self.coordinator.data
        if currentBucket in self.coordinator.hass.data[DOMAIN]["priceEntityCache"]:
            self._attr_native_value = self.coordinator.hass.data[DOMAIN]["priceEntityCache"][currentBucket]
        else:
          self._attr_native_value = None  


class PricePeakEntity(SensorEntity): #CoordinatorEntity

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    customName: str
    peak_threshold: int
    peak_distance: int
    peak_max_width: int
    peak_lookup_window: int
    peak_prominence: int
    trough: bool
    
    coordinator: CoordinatorEntity

    def __init__(self, coordinator: DataCoordinator, name: str, peak_threshold: int, peak_distance: int, peak_max_width: int, peak_lookup_window: int, peak_prominence: int, trough: bool = False):
        """Pass coordinator to CoordinatorEntity."""
        # super().__init__(coordinator)
        coordinator.registerCacheBuilder(self.buildCache)
        self.coordinator = coordinator
        self.customName = name
        self._attr_name = "Power Forecast Price Peak " + name
        self.peak_threshold = peak_threshold
        self.peak_distance = peak_distance
        self.peak_max_width = peak_max_width
        self.peak_lookup_window = peak_lookup_window
        self.peak_prominence = peak_prominence
        self.trough = trough
        if(self.peak_max_width is None):
            self.peak_max_width = 4

    def buildCache(self, hass: HomeAssistant, forecastsByBucket: dict[datetime, list[ForecastEntry]]) -> dict[datetime, Any]:
        pricePerDate: dict[datetime, float] = {}
        def forecastToPrice(forecast: ForecastEntry):
            return forecast.price
        for time, forecasts in forecastsByBucket.items():
            if(len(forecasts) > 0):
                pricePerDate[time] = min(list(map(forecastToPrice, forecasts)))
        sortedKeys = list(pricePerDate.keys())
        sortedKeys.sort()
        sortedPrices = []
        for key in sortedKeys:
            price = pricePerDate[key]
            if(self.trough) :
                price = price * -1
            sortedPrices.append(price)
        peaks, peakProperties = find_peaks(sortedPrices, threshold=self.peak_threshold, distance=self.peak_distance, width=[1, self.peak_max_width], wlen=self.peak_lookup_window, prominence=self.peak_prominence)
        
        cache : dict[datetime, float] = {}
        for i in range(len(peakProperties["left_ips"])):
            leftIpsBucket = sortedKeys[round(float(peakProperties["left_ips"][i]))]
            rightIpsBucket = sortedKeys[round(float(peakProperties["right_ips"][i]))]
            prominence = 1
            if "prominences" in peakProperties:
                prominence = peakProperties["prominences"][i] 

            currentBucket = leftIpsBucket
            while(currentBucket <= rightIpsBucket):
                cache[currentBucket] = prominence
                currentBucket = currentBucket + timedelta(minutes=15)
        hass.data[DOMAIN]["pricePeakCache_"+self.customName] = cache

        if SAVE_PICTURES:

            def formatTime(time: datetime):
                if(time.hour % 6 == 0 and time.minute == 0):
                    return time.strftime("%c")
                else:
                    return ""
            plt.figure()
            plt.xticks(rotation=45, ha='right', ticks=sortedKeys, labels=list(map(formatTime, sortedKeys)))
            plt.subplots_adjust(bottom=0.50)
            plt.plot(sortedKeys, sortedPrices)
            plt.plot(cache.keys(), cache.values(), "bo")
            plt.savefig('/tmp/PricePeakEntity'+self.customName+'.png')




    async def async_update(self):
        await self.coordinator.async_request_refresh()
        currentBucket = self.coordinator.data
        if currentBucket in self.hass.data[DOMAIN]["pricePeakCache_"+self.customName]:
            self._attr_native_value = self.hass.data[DOMAIN]["pricePeakCache_"+self.customName][currentBucket]
        else:
          self._attr_native_value = 0.0  