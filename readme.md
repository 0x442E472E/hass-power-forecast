# Power Forecast (Proof of Concept)
This integration will detect the lowest price for electricity out of multiple sources (like solar or Tibber) and provide some sensors to make use of it.

*This is just a proof of concept and i'm a beginner in Home Assistant and Python*

## Installation
Move `custom_components/power_forecast` to the config directory of your Home Assitant installation.  
You also need to provide `scipy` until i have figured out how to ship it as a dependency. With the default Home Assistant Docker image it could look like this:  
```
# apk add py3-scipy (If this won’t work, try py-scipy)
# Create symbolic link:
# ln -s /usr/lib/python3.10/site-packages/scipy /usr/local/lib/python3.10/site-packages/scipy
```

## Configuration
```yaml
sensor:
  - platform: power_forecast
    apis:
      tibber:
        token: <token> # Your personal tibber token
      forecast_solar:
        urls:
          - <url> # one of multiple urls for https://doc.forecast.solar. The results will be summarized.
        watt_threshold: 1500 # Filter out periods with low yield
        price: 0.065 # The cost to assume for your own generated energy
    sensors:
      peak:
        - name: Heatpump
          peak_distance: 16 # Amount of time slots between peaks
          peak_max_width: 12 # Amount of time slots 
          peak_lookup_window: 16 # Amount of time slots 
          peak_prominence: 0.01
#          peak_threshold: 
#          trough: 
```

A single time slot currently has a fixed length of 15 minutes.


## Usage
This integration provides the following sensors:  
**sensor.power_forecast_lowest_price:** Contains the current lowest price  
**sensor.power_forecast_sorted_price_level:** Assigns monotonic increasing numbers to every time slot, starting with 0 at the slot with the lowest price. This is useful for devices that need to run for a specific duration per day and the time doesn't matter. Example: A pool pump that needs to run for e.g. 10 hours per day.  
**sensor.power_forecast_price_peak_<name>:** Contains a value >0 when there is a price spike, with the exact value being the prominence of the spike. This could be used for example for a heat pump, that needs to run the whole time, but it's ok when it doesn't run for up to 3 hours (`peak_max_width`) as long as it has at least 4 hours to heat up between peaks (`peak_distance`).  
  
This integration also creates some images in `/tmp/` to visualize the prices.