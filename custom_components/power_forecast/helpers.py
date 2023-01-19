from dataclasses import dataclass

from datetime import timedelta,datetime
import logging
_LOGGER = logging.getLogger(__name__)

@dataclass
class ForecastEntry:
    price: float
    startingAt: datetime

def bucket(objectDatetime: datetime):
    return datetime(objectDatetime.year, objectDatetime.month, objectDatetime.day, objectDatetime.hour, int(objectDatetime.minute / 15) * 15, tzinfo=objectDatetime.tzinfo)

def fillForecastHoles(forecasts: list[ForecastEntry]) -> list[ForecastEntry]:
    result = []
    for i in range(len(forecasts) - 2):
        thisBucket = bucket(forecasts[i].startingAt)
        nextBucket = bucket(forecasts[i+1].startingAt)
        currentBucket = thisBucket + timedelta(minutes=15)
        currentForecast = forecasts[i]
        currentForecast.startingAt = thisBucket
        result.append(forecasts[i])
        while currentBucket != nextBucket:
            nextForecast = ForecastEntry(currentForecast.price, currentBucket)
            result.append(nextForecast)
            currentBucket = currentBucket + timedelta(minutes=15)
    lastForecast = forecasts[len(forecasts) - 1]
    result.append(ForecastEntry(lastForecast.price, bucket(lastForecast.startingAt)))
    return result