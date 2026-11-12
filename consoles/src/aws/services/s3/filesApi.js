/* S3 Files (service s3files, rest-json) and FSx for OpenZFS (service fsx, JSON 1.1) native-wire calls. */
import { awsJson, awsRest } from "../../../common/wire.js";
import * as ec2 from "../ec2/api.js";

const F = (method, path, opts) => awsRest("s3files", method, path, opts);
export const listFileSystems = async () => (await F("GET", "/file-systems")).fileSystems || [];
export const createFileSystem = ({ bucket, prefix, roleArn, name }) => F("POST", "/file-systems", { body: {
  bucket: `arn:aws:s3:::${bucket}`, ...(prefix ? { prefix } : {}), roleArn, ...(name ? { tags: [{ key: "Name", value: name }] } : {}) } });
export const deleteFileSystem = (id) => F("DELETE", `/file-systems/${id}`);
export const listMountTargets = async (id) => (await F("GET", `/file-systems/${id}/mount-targets`)).mountTargets || [];
export const createMountTarget = (id, { subnetId, securityGroups }) => F("POST", `/file-systems/${id}/mount-targets`, { body: { subnetId, ...(securityGroups?.length ? { securityGroups } : {}) } });
export const deleteMountTarget = (id) => F("DELETE", `/mount-targets/${id}`);
export const listFsAccessPoints = async (id) => (await F("GET", `/file-systems/${id}/access-points`)).accessPoints || [];
export const createFsAccessPoint = (id, body) => F("POST", `/file-systems/${id}/access-points`, { body });
export const deleteFsAccessPoint = (id) => F("DELETE", `/access-points/${id}`);
export async function getFsPolicy(id) { try { return (await F("GET", `/file-systems/${id}/policy`)).policy || ""; } catch (e) { if (e.status === 404) return ""; throw e; } }
export const putFsPolicy = (id, policy) => F("PUT", `/file-systems/${id}/policy`, { body: { policy } });
export const deleteFsPolicy = (id) => F("DELETE", `/file-systems/${id}/policy`);
export const getSync = (id) => F("GET", `/file-systems/${id}/synchronization-configuration`);
export const putSync = (id, body) => F("PUT", `/file-systems/${id}/synchronization-configuration`, { body });
export const listFiles = async (id, path) => (await F("GET", `/file-systems/${id}/files`, { query: { path } })).entries || [];
export const writeFile = (id, path, content) => F("PUT", `/file-systems/${id}/file`, { query: { path }, body: { content } });
export const readFile = async (id, path) => { const r = await F("GET", `/file-systems/${id}/file`, { query: { path } }); return atob(r.contentBase64); };
export const deleteFile = (id, path) => F("DELETE", `/file-systems/${id}/file`, { query: { path } });
export const makeDir = (id, path) => F("POST", `/file-systems/${id}/directories`, { body: { path } });
export const describeSubnets = ec2.describeSubnets;
export const describeSecurityGroups = ec2.describeSecurityGroups;

const X = (op, body = {}) => awsJson("fsx", `AmazonFSx.${op}`, body, { version: "1.1" });
export const fsxFileSystems = async () => (await X("DescribeFileSystems")).FileSystems || [];
export const fsxVolumes = async () => (await X("DescribeVolumes")).Volumes || [];
export const fsxCreateFileSystem = ({ capacity, throughput, deployment, subnetId }) => X("CreateFileSystem", { FileSystemType: "OPENZFS", StorageCapacity: Number(capacity), SubnetIds: [subnetId],
  OpenZFSConfiguration: { DeploymentType: deployment, ThroughputCapacity: Number(throughput) } });
export const fsxCreateVolume = (parent, name) => X("CreateVolume", { VolumeType: "OPENZFS", Name: name, OpenZFSConfiguration: { ParentVolumeId: parent } });
export const fsxAttachments = async () => (await X("DescribeS3AccessPointAttachments")).S3AccessPointAttachments || [];
export const fsxAttach = ({ name, volumeId, uid, gid, vpcId, policy }) => X("CreateAndAttachS3AccessPoint", { Name: name, Type: "OPENZFS",
  OpenZFSConfiguration: { VolumeId: volumeId, FileSystemIdentity: { Type: "POSIX", PosixUser: { Uid: Number(uid), Gid: Number(gid) } } },
  S3AccessPoint: { ...(vpcId ? { VpcConfiguration: { VpcId: vpcId } } : {}), ...(policy ? { Policy: policy } : {}) } });
export const fsxDetach = (name) => X("DetachAndDeleteS3AccessPoint", { Name: name });
export const fsxPutFile = (volumeId, path, content) => X("VyomiPutVolumeFile", { VolumeId: volumeId, Path: path, Content: content });
export const fsxListFiles = async (volumeId) => (await X("VyomiListVolumeFiles", { VolumeId: volumeId })).Files || [];
export const describeVpcs = ec2.describeVpcs;
