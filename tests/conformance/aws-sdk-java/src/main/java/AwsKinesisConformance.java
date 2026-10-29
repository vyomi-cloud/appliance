import java.net.URI;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.core.SdkBytes;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.kinesis.KinesisClient;
import software.amazon.awssdk.services.kinesis.model.*;

/**
 * Real AWS SDK for Java v2 conformance for Amazon Kinesis Data Streams against Vyomi,
 * with only the endpoint changed.
 *
 *   ENDPOINT=http://localhost:9000 mvn -q -B compile exec:java -Dexec.mainClass=AwsKinesisConformance
 *
 * One [PASS]/[FAIL] line per check; exit 1 on any failure.
 */
public class AwsKinesisConformance {
    static int fails = 0;

    static void check(boolean ok, String what, Object detail) {
        if (ok) { System.out.println("[PASS] " + what); return; }
        fails++;
        System.out.println("[FAIL] " + what + " :: " + detail);
    }

    static <T> T run(String what, Callable<T> c) {
        try { T v = c.call(); check(true, what, null); return v; }
        catch (Exception e) { check(false, what, e); return null; }
    }

    static String code(Exception e) {
        return e instanceof KinesisException k && k.awsErrorDetails() != null ? k.awsErrorDetails().errorCode() : String.valueOf(e);
    }

    public static void main(String[] args) throws Exception {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://localhost:9000");
        KinesisClient k = KinesisClient.builder()
            .endpointOverride(URI.create(endpoint)).region(Region.US_EAST_1)
            .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test")))
            .build();
        String name = "java-kin-" + Long.toString(System.nanoTime() % 1_000_000_000L, 36);

        run("CreateStream", () -> k.createStream(CreateStreamRequest.builder().streamName(name).shardCount(2).build()));
        try {
            k.createStream(CreateStreamRequest.builder().streamName(name).shardCount(1).build());
            check(false, "duplicate CreateStream -> ResourceInUseException", "no error");
        } catch (Exception e) {
            check(e instanceof ResourceInUseException, "duplicate CreateStream -> ResourceInUseException", code(e));
        }

        DescribeStreamResponse d = run("DescribeStream", () -> k.describeStream(DescribeStreamRequest.builder().streamName(name).build()));
        List<Shard> shards = d == null ? List.of() : d.streamDescription().shards();
        check(d != null && d.streamDescription().streamStatus() == StreamStatus.ACTIVE && shards.size() == 2,
              "stream is ACTIVE with 2 shards", d);
        String arn = d == null ? "" : d.streamDescription().streamARN();
        check(arn.startsWith("arn:aws:kinesis:us-east-1:") && arn.endsWith(":stream/" + name), "stream ARN shape", arn);
        check(!shards.isEmpty() && shards.get(0).hashKeyRange().startingHashKey().equals("0"), "first shard starts at hash key 0", shards);

        DescribeStreamSummaryResponse s = run("DescribeStreamSummary",
            () -> k.describeStreamSummary(DescribeStreamSummaryRequest.builder().streamName(name).build()));
        check(s != null && s.streamDescriptionSummary().openShardCount() == 2
              && s.streamDescriptionSummary().retentionPeriodHours() == 24, "summary: 2 open shards, 24h retention", s);
        ListStreamsResponse ls = run("ListStreams", () -> k.listStreams(ListStreamsRequest.builder().build()));
        check(ls != null && ls.streamNames().contains(name), "ListStreams contains the stream", ls);

        PutRecordResponse p = run("PutRecord", () -> k.putRecord(PutRecordRequest.builder().streamName(name)
            .partitionKey("pk-1").data(SdkBytes.fromUtf8String("hello-java")).build()));
        check(p != null && p.sequenceNumber().length() == 56, "PutRecord returns a 56-digit sequence number", p);
        PutRecordsResponse pr = run("PutRecords", () -> k.putRecords(PutRecordsRequest.builder().streamName(name).records(
            List.of(0, 1, 2, 3, 4).stream().map(i -> PutRecordsRequestEntry.builder().partitionKey("k" + i)
                .data(SdkBytes.fromUtf8String("rec-" + i)).build()).toList()).build()));
        check(pr != null && pr.failedRecordCount() == 0 && pr.records().size() == 5, "PutRecords: 5 records, none failed", pr);

        int total = 0;
        for (Shard sh : shards) {
            String it = k.getShardIterator(GetShardIteratorRequest.builder().streamName(name).shardId(sh.shardId())
                .shardIteratorType(ShardIteratorType.TRIM_HORIZON).build()).shardIterator();
            total += k.getRecords(GetRecordsRequest.builder().shardIterator(it).build()).records().size();
        }
        check(total == 6, "GetRecords reads back all 6 records across the shards", total);
        if (p != null) {
            String it = k.getShardIterator(GetShardIteratorRequest.builder().streamName(name).shardId(p.shardId())
                .shardIteratorType(ShardIteratorType.AT_SEQUENCE_NUMBER).startingSequenceNumber(p.sequenceNumber()).build()).shardIterator();
            GetRecordsResponse g = k.getRecords(GetRecordsRequest.builder().shardIterator(it).limit(1).build());
            check(g.records().size() == 1 && g.records().get(0).data().asUtf8String().equals("hello-java")
                  && g.records().get(0).partitionKey().equals("pk-1"), "AT_SEQUENCE_NUMBER returns the exact record", g);
            check(g.nextShardIterator() != null, "GetRecords returns a NextShardIterator", g);
        }
        try {
            k.getRecords(GetRecordsRequest.builder().shardIterator("garbage").build());
            check(false, "bad iterator -> InvalidArgumentException", "no error");
        } catch (Exception e) {
            check(e instanceof InvalidArgumentException, "bad iterator -> InvalidArgumentException", code(e));
        }

        run("SplitShard", () -> k.splitShard(SplitShardRequest.builder().streamName(name).shardToSplit(shards.get(0).shardId())
            .newStartingHashKey("85070591730234615865843651857942052864").build()));
        ListShardsResponse all = run("ListShards", () -> k.listShards(ListShardsRequest.builder().streamName(name).build()));
        check(all != null && all.shards().size() == 4, "ListShards: parent + 2 children + untouched shard", all);
        run("IncreaseStreamRetentionPeriod", () -> k.increaseStreamRetentionPeriod(IncreaseStreamRetentionPeriodRequest.builder()
            .streamName(name).retentionPeriodHours(72).build()));
        run("StartStreamEncryption", () -> k.startStreamEncryption(StartStreamEncryptionRequest.builder().streamName(name)
            .encryptionType(EncryptionType.KMS).keyId("alias/aws/kinesis").build()));
        DescribeStreamSummaryResponse s2 = k.describeStreamSummary(DescribeStreamSummaryRequest.builder().streamName(name).build());
        check(s2.streamDescriptionSummary().retentionPeriodHours() == 72
              && s2.streamDescriptionSummary().encryptionType() == EncryptionType.KMS, "retention and encryption are reflected", s2);

        run("AddTagsToStream", () -> k.addTagsToStream(AddTagsToStreamRequest.builder().streamName(name).tags(Map.of("env", "dev", "team", "core")).build()));
        ListTagsForStreamResponse tags = run("ListTagsForStream", () -> k.listTagsForStream(ListTagsForStreamRequest.builder().streamName(name).build()));
        check(tags != null && tags.tags().size() == 2, "two tags are listed", tags);

        RegisterStreamConsumerResponse rc = run("RegisterStreamConsumer", () -> k.registerStreamConsumer(
            RegisterStreamConsumerRequest.builder().streamARN(arn).consumerName("analytics").build()));
        check(rc != null && rc.consumer().consumerStatus() == ConsumerStatus.ACTIVE, "consumer is ACTIVE", rc);
        DescribeStreamConsumerResponse dc = run("DescribeStreamConsumer", () -> k.describeStreamConsumer(
            DescribeStreamConsumerRequest.builder().streamARN(arn).consumerName("analytics").build()));
        check(dc != null && dc.consumerDescription().streamARN().equals(arn), "consumer description points at the stream", dc);
        try {
            k.deleteStream(DeleteStreamRequest.builder().streamName(name).build());
            check(false, "DeleteStream blocked by a registered consumer", "no error");
        } catch (Exception e) {
            check(e instanceof ResourceInUseException, "DeleteStream blocked by a registered consumer", code(e));
        }
        run("DeleteStream enforceConsumerDeletion", () -> k.deleteStream(DeleteStreamRequest.builder().streamName(name).enforceConsumerDeletion(true).build()));
        try {
            k.describeStream(DescribeStreamRequest.builder().streamName(name).build());
            check(false, "DescribeStream after delete -> ResourceNotFoundException", "no error");
        } catch (Exception e) {
            check(e instanceof ResourceNotFoundException, "DescribeStream after delete -> ResourceNotFoundException", code(e));
        }

        if (fails > 0) { System.out.println(fails + " check(s) failed"); System.exit(1); }
        System.out.println("all checks passed");
    }
}
