import boto3

ct = boto3.client("cloudtrail")
ct.create_trail(Name="facilities-trail", S3BucketName="facilities-docs", S3KeyPrefix="audit", IsMultiRegionTrail=False)
ct.start_logging(Name="facilities-trail")
print("trail facilities-trail logging:", ct.get_trail_status(Name="facilities-trail")["IsLogging"])
