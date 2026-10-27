import com.google.api.gax.core.NoCredentialsProvider;
import com.google.api.gax.rpc.AbortedException;
import com.google.api.gax.rpc.AlreadyExistsException;
import com.google.api.gax.rpc.InvalidArgumentException;
import com.google.api.gax.rpc.NotFoundException;
import com.google.cloud.workflows.v1.CreateWorkflowRequest;
import com.google.cloud.workflows.v1.DeleteWorkflowRequest;
import com.google.cloud.workflows.v1.GetWorkflowRequest;
import com.google.cloud.workflows.v1.ListWorkflowsRequest;
import com.google.cloud.workflows.v1.UpdateWorkflowRequest;
import com.google.cloud.workflows.v1.Workflow;
import com.google.cloud.workflows.v1.WorkflowsClient;
import com.google.cloud.workflows.v1.WorkflowsSettings;
import com.google.protobuf.FieldMask;

/**
 * Real google-cloud-workflows (Java, REST/httpjson transport) conformance against Vyomi's Workflows
 * API. Endpoint comes from env ENDPOINT (default http://127.0.0.1:9000), project from PROJECT.
 * (The executions client is gRPC-only; executions are covered by the gcloud CLI suite.)
 * One [PASS]/[FAIL] line per check; exits non-zero on any failure.
 */
public class WorkflowsConformance {
  static int pass = 0, fail = 0;

  static void check(String name, boolean ok, String detail) {
    System.out.println("[" + (ok ? "PASS" : "FAIL") + "] " + name
        + (!ok && detail != null && !detail.isEmpty() ? " :: " + detail : ""));
    if (ok) pass++; else fail++;
  }

  static final String SRC = "main:\n  steps:\n    - init:\n        assign:\n          - greeting: \"Hello from Java\"\n    - done:\n        return: ${greeting}\n";
  static final String SRC2 = "main:\n  steps:\n    - done:\n        return: \"v2\"\n";

  public static void main(String[] args) throws Exception {
    String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
    String project = System.getenv().getOrDefault("PROJECT", "java-wf-proj");
    String region = "us-central1";
    System.out.println("== google-cloud-workflows (Java) against " + endpoint + " project=" + project + " ==");

    WorkflowsSettings settings = WorkflowsSettings.newHttpJsonBuilder()
        .setCredentialsProvider(NoCredentialsProvider.create())
        .setTransportChannelProvider(WorkflowsSettings.defaultHttpJsonTransportProviderBuilder()
            .setEndpoint(endpoint).build())
        .build();
    String id = "java-wf-" + (System.currentTimeMillis() % 1000000);
    String parent = "projects/" + project + "/locations/" + region;
    String name = parent + "/workflows/" + id;

    try (WorkflowsClient c = WorkflowsClient.create(settings)) {
      try {
        Workflow w = c.createWorkflowAsync(CreateWorkflowRequest.newBuilder().setParent(parent).setWorkflowId(id)
            .setWorkflow(Workflow.newBuilder().setDescription("created by the Java SDK").putLabels("env", "dev")
                .setSourceContents(SRC).build()).build()).get();
        check("CreateWorkflow (LRO) -> Workflow ACTIVE with revision", w.getState() == Workflow.State.ACTIVE
            && w.getRevisionId().startsWith("000001-") && name.equals(w.getName()), w.toString());
      } catch (Exception e) { check("CreateWorkflow (LRO) -> Workflow ACTIVE with revision", false, e.toString()); }

      try {
        c.createWorkflowAsync(CreateWorkflowRequest.newBuilder().setParent(parent).setWorkflowId(id)
            .setWorkflow(Workflow.newBuilder().setSourceContents(SRC).build()).build()).get();
        check("CreateWorkflow duplicate -> ALREADY_EXISTS", false, "no error");
      } catch (Exception e) {
        // HTTP 409 maps to ABORTED in gax's REST transport; the body carries status ALREADY_EXISTS.
        Throwable t = e.getCause() != null ? e.getCause() : e;
        check("CreateWorkflow duplicate -> ALREADY_EXISTS", t instanceof AlreadyExistsException || t instanceof AbortedException, e.toString());
      }

      try {
        c.createWorkflowAsync(CreateWorkflowRequest.newBuilder().setParent(parent).setWorkflowId("1-bad")
            .setWorkflow(Workflow.newBuilder().setSourceContents(SRC).build()).build()).get();
        check("CreateWorkflow bad id -> INVALID_ARGUMENT", false, "no error");
      } catch (Exception e) {
        Throwable t = e.getCause() != null ? e.getCause() : e;
        check("CreateWorkflow bad id -> INVALID_ARGUMENT", t instanceof InvalidArgumentException, e.toString());
      }

      try {
        Workflow g = c.getWorkflow(GetWorkflowRequest.newBuilder().setName(name).build());
        check("GetWorkflow (ACTIVE, description, labels, source, service account)", g.getState() == Workflow.State.ACTIVE
            && "created by the Java SDK".equals(g.getDescription()) && "dev".equals(g.getLabelsMap().get("env"))
            && SRC.equals(g.getSourceContents()) && !g.getServiceAccount().isEmpty(), g.toString());
      } catch (Exception e) { check("GetWorkflow (ACTIVE, description, labels, source, service account)", false, e.toString()); }

      try {
        c.getWorkflow(GetWorkflowRequest.newBuilder().setName(parent + "/workflows/missing-" + id).build());
        check("GetWorkflow missing -> NOT_FOUND", false, "no error");
      } catch (NotFoundException e) { check("GetWorkflow missing -> NOT_FOUND", true, "");
      } catch (Exception e) { check("GetWorkflow missing -> NOT_FOUND", false, e.toString()); }

      try {
        boolean found = false;
        for (Workflow x : c.listWorkflows(ListWorkflowsRequest.newBuilder().setParent(parent).build()).iterateAll())
          found = found || name.equals(x.getName());
        check("ListWorkflows contains the workflow", found, "");
      } catch (Exception e) { check("ListWorkflows contains the workflow", false, e.toString()); }

      try {
        Workflow u = c.updateWorkflowAsync(UpdateWorkflowRequest.newBuilder()
            .setUpdateMask(FieldMask.newBuilder().addPaths("description").addPaths("labels").build())
            .setWorkflow(Workflow.newBuilder().setName(name).setDescription("updated").putLabels("team", "core").build()).build()).get();
        Workflow g = c.getWorkflow(GetWorkflowRequest.newBuilder().setName(name).build());
        check("UpdateWorkflow (description + labels) keeps the revision", "updated".equals(u.getDescription())
            && "core".equals(g.getLabelsMap().get("team")) && g.getRevisionId().startsWith("000001-"), g.toString());
      } catch (Exception e) { check("UpdateWorkflow (description + labels) keeps the revision", false, e.toString()); }

      try {
        Workflow u = c.updateWorkflowAsync(UpdateWorkflowRequest.newBuilder()
            .setUpdateMask(FieldMask.newBuilder().addPaths("source_contents").build())
            .setWorkflow(Workflow.newBuilder().setName(name).setSourceContents(SRC2).build()).build()).get();
        check("UpdateWorkflow source bumps the revision", u.getRevisionId().startsWith("000002-"), u.toString());
      } catch (Exception e) { check("UpdateWorkflow source bumps the revision", false, e.toString()); }

      try {
        c.deleteWorkflowAsync(DeleteWorkflowRequest.newBuilder().setName(name).build()).get();
        boolean gone = false;
        try { c.getWorkflow(GetWorkflowRequest.newBuilder().setName(name).build()); } catch (NotFoundException e) { gone = true; }
        check("DeleteWorkflow (LRO) removes the workflow", gone, "");
      } catch (Exception e) { check("DeleteWorkflow (LRO) removes the workflow", false, e.toString()); }
    }
    System.out.println("RESULT pass=" + pass + " fail=" + fail);
    if (fail > 0) System.exit(1);
  }
}
