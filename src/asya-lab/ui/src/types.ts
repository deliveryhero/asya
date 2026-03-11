export type ConnectionState =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "degraded"
  | "error";

export type ActorState =
  | "running"
  | "scaled-to-zero"
  | "error"
  | "processing"
  | "pending";

export interface ActorInfo {
  name: string;
  handler: string;
  image: string;
  transport: string;
  labels: Record<string, string>;
}

export interface ActorStatus {
  replicas: number;
  desiredReplicas: number;
  queueDepth: number;
  state: ActorState;
  lastError?: string;
}

export interface LogLine {
  timestamp: string;
  actor: string;
  level: "debug" | "info" | "warn" | "error";
  message: string;
}

export interface TaskProgress {
  id: string;
  status: string;
  progressPercent: number;
  currentActor: string;
  actorsCompleted: number;
  totalActors: number;
  message: string;
}

export interface GraphNode {
  id: string;
  type: "router" | "actor";
  role: string;
  label: string;
  entrypoint?: boolean;
  exitpoint?: boolean;
  handler?: string;
  image?: string;
  condition?: string;
  mutations?: string[];
}

export interface GraphEdge {
  source: string;
  target: string;
  type: "sequential" | "true" | "false" | "except" | "fanout";
  label?: string;
}

export interface GraphGroup {
  id: string;
  type: "try" | "finally";
  nodes: string[];
}

export interface FlowGraph {
  flow: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  groups: GraphGroup[];
}

export interface AsyaContextValue {
  actors: ActorInfo[];
  getActorStatus(name: string): ActorStatus | null;
  subscribeLogs(actorName: string): () => void;
  logLines: LogLine[];
  taskProgress: TaskProgress | null;
  subscribeTask(taskId: string): () => void;
  flowName: string;
  context: string;
  readonly: boolean;
  connectionState: ConnectionState;
  connectionError?: string;
  onNodeClick?: (nodeId: string) => void;
}
