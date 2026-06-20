package cloud.vyomi.probe;

import java.util.Map;

/** One implementation per cloud. {@link #probe()} runs a full object-store +
 *  NoSQL lifecycle using that cloud's NATIVE SDK and returns a step report. */
public interface CloudProbe {
    /** "aws" | "gcp" | "azure" */
    String cloud();

    /** Run the lifecycle; never throws — failures are captured in the report. */
    Map<String, Object> probe();

    /** Read one object back via the native object-store SDK — used to verify a
     *  file written from the appliance console (UI) is readable by the SDK.
     *  For Azure, {@code bucket} is the container. Never throws. */
    Map<String, Object> getObject(String bucket, String key);

    /** Same, but with an explicit object-store namespace. For Azure this is the
     *  storage account (so a console upload to any account is readable); AWS/GCP
     *  ignore it (the bucket is globally addressed). Blank → cloud default. */
    default Map<String, Object> getObject(String bucket, String key, String account) {
        return getObject(bucket, key);
    }
}
