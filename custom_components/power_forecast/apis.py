from dataclasses import dataclass
import voluptuous as vol
from requests_futures.sessions import FuturesSession

from datetime import datetime, timezone, timedelta
import logging
_LOGGER = logging.getLogger(__name__)
import json
import pytz


from .helpers import ForecastEntry,fillForecastHoles


class ForecastApi:
     async def getForecast(self) -> list[ForecastEntry]:
        pass

class TibberApi(ForecastApi):

    access_token: str

    def __init__(self, access_token: str):
        self.access_token = access_token


    async def getForecast(self) -> list[ForecastEntry]:
        headers = {
            'Authorization' : 'Bearer ' + self.access_token,
            'Content-Type' : "application/json"
            }
        query = """
        {
            viewer {
                homes {
                currentSubscription{
                    priceInfo{
                    today {
                        total
                        startsAt
                    }
                    tomorrow {
                        total
                        startsAt
                    }
                    }
                }
                }
            }
        }
        """
        # query = """{\n  viewer {\n    homes {\n      currentSubscription{\n        priceInfo{\n          today {\n            total\n            startsAt\n          }\n          tomorrow {\n            total\n            startsAt\n          }\n        }\n      }\n    }\n  }\n}"""  
        session = FuturesSession()
        response = session.post("https://api.tibber.com/v1-beta/gql", headers = headers, json={"query": query}).result()
        jsonResponse = response.json()

        now = datetime.now(timezone.utc)
   
        def extractEntry(jsonObject):
            return  ForecastEntry(jsonObject["total"], datetime.fromisoformat(jsonObject["startsAt"]).astimezone(pytz.utc))

        if("errors" in jsonResponse):
            raise IOError("Tibber responded with: " + json.dumps(jsonResponse["errors"]))
        if("error" in jsonResponse):
            raise IOError("Tibber responded with: " + json.dumps(jsonResponse["error"]))

        today = list(map(extractEntry, jsonResponse["data"]["viewer"]["homes"][0]["currentSubscription"]["priceInfo"]["today"]))
        tomorrow = list(map(extractEntry, jsonResponse["data"]["viewer"]["homes"][0]["currentSubscription"]["priceInfo"]["tomorrow"]))
        return fillForecastHoles(today + tomorrow)


class ForecastSolarApi(ForecastApi):

    urls: list[str]
    minimumWatt: int
    pricePerKwh: float

    def __init__(self, urls:  list[str], minimumWatt: int, pricePerKwh: float):
        self.urls = urls
        self.minimumWatt = minimumWatt 
        self.pricePerKwh = pricePerKwh

    def bucket(self, objectDatetime: datetime):
        return datetime(objectDatetime.year, objectDatetime.month, objectDatetime.day, objectDatetime.hour, int(objectDatetime.minute / 15) * 15, tzinfo=objectDatetime.tzinfo)


    async def getForecast(self) -> list[ForecastEntry]:
        timeToWatts: dict[datetime, int] = {}

        session = FuturesSession()
        headers = {
            "Content-Type": "application/json"
        }
        for url in self.urls:
            response = session.get(url, headers=headers).result()
            jsonResponse = response.json()
            if("result" not in jsonResponse or len(jsonResponse["result"]) == 0):
                raise IOError("forecast.solar responded with: " + json.dumps(jsonResponse["message"]))
            watts = jsonResponse["result"]["watts"]
            previousTime = None
            for timeStr, watts in watts.items():
                parsedTime = datetime.strptime(timeStr, '%Y-%m-%d %H:%M:%S').astimezone().astimezone(pytz.utc)
                currentTime = self.bucket(parsedTime)
                if previousTime is not None:
                    bucketTime = previousTime
                    while bucketTime < currentTime:
                        timeToWatts.setdefault(bucketTime, 0)
                        timeToWatts[bucketTime] = timeToWatts[bucketTime] + watts
                        bucketTime += timedelta(minutes=15)
                previousTime = currentTime
            
        result = list()
        for time, watts in timeToWatts.items():
            if(watts > self.minimumWatt):
                result.append(ForecastEntry(self.pricePerKwh, time))

        def sortByTime(entry: ForecastEntry):
            return entry.startingAt
        result.sort(key = sortByTime)
        
        return result
