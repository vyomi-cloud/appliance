package cloud.vyomi.probe;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

@RestController
public class ProbeController {

    /** cloud -> probe, populated from every CloudProbe bean Spring finds. */
    private final Map<String, CloudProbe> probes = new TreeMap<>();

    public ProbeController(List<CloudProbe> all) {
        for (CloudProbe p : all) probes.put(p.cloud(), p);
    }

    @GetMapping("/healthz")
    public Map<String, Object> health() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("status", "ok");
        m.put("clouds", probes.keySet());
        return m;
    }

    @GetMapping("/probe/{cloud}")
    public ResponseEntity<Map<String, Object>> probe(@PathVariable("cloud") String cloud) {
        CloudProbe p = probes.get(cloud.toLowerCase());
        if (p == null) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("ok", false);
            m.put("error", "unknown or unwired cloud: " + cloud);
            m.put("available", probes.keySet());
            return ResponseEntity.badRequest().body(m);
        }
        Map<String, Object> result = p.probe(); // never throws; failures are in the report
        boolean ok = Boolean.TRUE.equals(result.get("ok"));
        return ok ? ResponseEntity.ok(result) : ResponseEntity.status(502).body(result);
    }
}
