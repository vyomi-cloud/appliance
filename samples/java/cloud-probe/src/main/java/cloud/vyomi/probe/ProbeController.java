package cloud.vyomi.probe;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestParam;
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

    /** Read an object written from the console (UI). Azure: bucket = container,
     *  optional account = storage account (defaults to devstoreaccount1).
     *  e.g. GET /object/aws?bucket=my-bucket&key=path/to/file.txt
     *       GET /object/azure?account=stcloudlearn&bucket=app-data&key=hello.txt */
    @GetMapping("/object/{cloud}")
    public ResponseEntity<Map<String, Object>> getObject(@PathVariable("cloud") String cloud,
            @RequestParam("bucket") String bucket, @RequestParam("key") String key,
            @RequestParam(value = "account", required = false) String account) {
        CloudProbe p = probes.get(cloud.toLowerCase());
        if (p == null) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("ok", false);
            m.put("error", "unknown or unwired cloud: " + cloud);
            m.put("available", probes.keySet());
            return ResponseEntity.badRequest().body(m);
        }
        Map<String, Object> res = p.getObject(bucket, key, account);
        boolean ok = Boolean.TRUE.equals(res.get("ok"));
        return ok ? ResponseEntity.ok(res) : ResponseEntity.status(502).body(res);
    }

    /** Read a NoSQL item written from the console (or via PUT below) through the
     *  native NoSQL SDK. table = DynamoDB table | Firestore collection | Cosmos
     *  container; database = Cosmos database (ignored by AWS/GCP).
     *  e.g. GET /item/aws?table=my-table&id=item-1
     *       GET /item/azure?database=probe_db&table=people&id=item-1 */
    @GetMapping("/item/{cloud}")
    public ResponseEntity<Map<String, Object>> getItem(@PathVariable("cloud") String cloud,
            @RequestParam("table") String table, @RequestParam("id") String id,
            @RequestParam(value = "database", required = false) String database) {
        CloudProbe p = probes.get(cloud.toLowerCase());
        if (p == null) return unknownCloud(cloud);
        Map<String, Object> res = p.getItem(table, id, database);
        boolean ok = Boolean.TRUE.equals(res.get("ok"));
        return ok ? ResponseEntity.ok(res) : ResponseEntity.status(502).body(res);
    }

    /** Write a small test item {id, msg:"hello-vyomi", n:1} via the native SDK,
     *  then read it back — so the GET endpoint can be validated end-to-end
     *  without depending on a console write. */
    @PutMapping("/item/{cloud}")
    public ResponseEntity<Map<String, Object>> putItem(@PathVariable("cloud") String cloud,
            @RequestParam("table") String table, @RequestParam("id") String id,
            @RequestParam(value = "database", required = false) String database) {
        CloudProbe p = probes.get(cloud.toLowerCase());
        if (p == null) return unknownCloud(cloud);
        Map<String, Object> res = p.putItem(table, id, database);
        boolean ok = Boolean.TRUE.equals(res.get("ok"));
        return ok ? ResponseEntity.ok(res) : ResponseEntity.status(502).body(res);
    }

    private ResponseEntity<Map<String, Object>> unknownCloud(String cloud) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("ok", false);
        m.put("error", "unknown or unwired cloud: " + cloud);
        m.put("available", probes.keySet());
        return ResponseEntity.badRequest().body(m);
    }
}
