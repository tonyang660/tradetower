# data-hub

Service placeholder for the data hub.

Responsibilities:
- market data ingestion
- normalization
- historical query access

accepting normalized candles from API Gateway
storing them in filesystem/Parquet
serving candle windows and ranges to Feature Factory
ensuring timestamps and ordering are clean