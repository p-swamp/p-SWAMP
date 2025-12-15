# Obtaining Power System Data from OpenInfraMap using Overpass Turbo
The power system data in this folder is obtained from [OpenInfraMap](https://openinframap.org).

To download the data, the [overpass turbo](https://overpass-turbo.eu/) service is used.

To use the overpass turbo page, a query is entered, which specifies the types of data to be collected, and from which locations. The query used to obtain the data used here can be found in the folder scandinavia/query.txt. Just copy-paste the query into overpass turbo and click "Run". You might be propted whether you actually want to show the large dataset in your browser. Just click yes, wait a couple of minutes, and click "Export" to download the data. The format used here was GeoJSON.

Plotting data from a GeoJSON-file in Python might be slow, especcially for large data sets. Therefore, the script "generate_numpy_data.py" loads the GeoJSON file and converts it into a format that can be plotted fast in Python.
