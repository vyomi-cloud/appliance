package cloud.vyomi.probe;

import java.util.Map;

/** One implementation per cloud. {@link #probe()} runs a full object-store +
 *  NoSQL lifecycle using that cloud's NATIVE SDK and returns a step report. */
public interface CloudProbe {
    /** "aws" | "gcp" | "azure" */
    String cloud();

    /** Run the lifecycle; never throws — failures are captured in the report. */
    Map<String, Object> probe();
}
