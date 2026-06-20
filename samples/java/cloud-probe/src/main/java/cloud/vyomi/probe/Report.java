package cloud.vyomi.probe;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Ordered, JSON-friendly step report. Each step records ok + a short detail
 *  so a failed probe pinpoints exactly which SDK operation broke. */
public class Report {
    private final String cloud;
    private final long startedAt = System.currentTimeMillis();
    private final List<Map<String, Object>> steps = new ArrayList<>();
    private boolean ok = true;

    public Report(String cloud) { this.cloud = cloud; }

    /** Record a step result. Returns this for chaining. */
    public Report step(String name, boolean stepOk, String detail) {
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("step", name);
        s.put("ok", stepOk);
        s.put("detail", detail == null ? "" : detail);
        steps.add(s);
        if (!stepOk) ok = false;
        return this;
    }

    public boolean ok() { return ok; }

    public Map<String, Object> toMap() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("cloud", cloud);
        m.put("ok", ok);
        m.put("elapsed_ms", System.currentTimeMillis() - startedAt);
        m.put("steps", steps);
        return m;
    }
}
