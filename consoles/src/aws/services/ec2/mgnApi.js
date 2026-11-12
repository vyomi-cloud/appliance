/* Application Migration Service (mgn) over its native rest-json wire: POST /<Operation>, SigV4-scoped "mgn". */
import { getRegion, restJson } from "../../../common/wire.js";

const amzDate = () => new Date().toISOString().replace(/[-:]|\.\d{3}/g, "");
function headers() {
  const d = amzDate();
  return { authorization: `AWS4-HMAC-SHA256 Credential=VYOMICONSOLE/${d.slice(0, 8)}/${getRegion()}/mgn/aws4_request, SignedHeaders=host;x-amz-date, Signature=0`, "x-amz-date": d };
}
const M = (op, body = {}) => restJson("POST", `/${op}`, { body, headers: headers() });

export const describeSourceServers = (filters) => M("DescribeSourceServers", { filters }).then((r) => r.items || []);
export const describeTemplates = () => M("DescribeReplicationConfigurationTemplates").then((r) => r.items || []);
export const createTemplate = (input) => M("CreateReplicationConfigurationTemplate", input);
export const registerSourceServer = (input) => M("RegisterSourceServer", input);
export const getReplication = (id) => M("GetReplicationConfiguration", { sourceServerID: id });
export const updateReplication = (id, input) => M("UpdateReplicationConfiguration", { sourceServerID: id, ...input });
export const getLaunch = (id) => M("GetLaunchConfiguration", { sourceServerID: id });
export const updateLaunch = (id, input) => M("UpdateLaunchConfiguration", { sourceServerID: id, ...input });
export const startTest = (ids) => M("StartTest", { sourceServerIDs: ids });
export const startCutover = (ids) => M("StartCutover", { sourceServerIDs: ids });
export const changeLifeCycle = (id, state) => M("ChangeServerLifeCycleState", { sourceServerID: id, lifeCycle: { state } });
export const finalizeCutover = (id) => M("FinalizeCutover", { sourceServerID: id });
export const terminateTargets = (ids) => M("TerminateTargetInstances", { sourceServerIDs: ids });
export const markArchived = (id) => M("MarkAsArchived", { sourceServerID: id });
export const disconnect = (id) => M("DisconnectFromService", { sourceServerID: id });
export const deleteSourceServer = (id) => M("DeleteSourceServer", { sourceServerID: id });
export const describeJobs = () => M("DescribeJobs").then((r) => r.items || []);
