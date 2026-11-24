/* GCP skin of the shared layered diagram (common/infra-diagram): Google API resource kinds -> layer / inbound-core-outbound.
 * Icons are the same Material outline icons the GCP lens already uses (no Google product icons). */
import LanOutlined from "@mui/icons-material/esm/LanOutlined.js";
import SecurityOutlined from "@mui/icons-material/esm/SecurityOutlined.js";
import MemoryOutlined from "@mui/icons-material/esm/MemoryOutlined.js";
import Inventory2Outlined from "@mui/icons-material/esm/Inventory2Outlined.js";
import StorageOutlined from "@mui/icons-material/esm/StorageOutlined.js";
import DirectionsRunOutlined from "@mui/icons-material/esm/DirectionsRunOutlined.js";
import MessageOutlined from "@mui/icons-material/esm/MessageOutlined.js";
import FunctionsOutlined from "@mui/icons-material/esm/FunctionsOutlined.js";
import DescriptionOutlined from "@mui/icons-material/esm/DescriptionOutlined.js";
import AltRoute from "@mui/icons-material/esm/AltRoute.js";
import KeyOutlined from "@mui/icons-material/esm/KeyOutlined.js";
import LockOutlined from "@mui/icons-material/esm/LockOutlined.js";
import BadgeOutlined from "@mui/icons-material/esm/BadgeOutlined.js";
import PublicOutlined from "@mui/icons-material/esm/PublicOutlined.js";
import Inventory from "@mui/icons-material/esm/Inventory.js";
import ScheduleOutlined from "@mui/icons-material/esm/ScheduleOutlined.js";
import SpeedOutlined from "@mui/icons-material/esm/SpeedOutlined.js";

const ICON = { network: LanOutlined, subnet: LanOutlined, firewall: SecurityOutlined, route: AltRoute, instance: MemoryOutlined, bucket: Inventory2Outlined, sql: StorageOutlined, run: DirectionsRunOutlined, topic: MessageOutlined, function: FunctionsOutlined, firestore: DescriptionOutlined, keyring: KeyOutlined, key: KeyOutlined, secret: LockOutlined, serviceaccount: BadgeOutlined, dns: PublicOutlined, registry: Inventory, scheduler: ScheduleOutlined, redis: SpeedOutlined };

export const GCP_PROFILE = {
  cloud: "gcp",
  usersLabel: "Users, browsers & external apps",
  primary: [
    ["edge", /^(subnet|firewall|route|address|dns)$/],
    ["data", /^(bucket|sql|firestore|redis|registry|keyring|key|secret)$/],
    ["compute", /^(instance|run|function|topic|subscription|scheduler|serviceaccount)$/],
  ],
  fallback: [],
  inbound: /^(subnet|firewall|route|address|dns)$/,
  outbound: /^(subscription|scheduler)$/,
  entry: /^(address|dns)$/,
  Icon: (n) => ICON[n.type] || StorageOutlined,
  typeLabel: (n) => n.type,
};
