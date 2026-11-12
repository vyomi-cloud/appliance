/* The portal's current subscription (Settings → Directories + subscriptions). */
import { createContext, useContext } from "react";
import { DEFAULT_SUBSCRIPTION } from "./arm.js";

export const SubscriptionCtx = createContext({ id: DEFAULT_SUBSCRIPTION, displayName: "" });
export const useSubscription = () => useContext(SubscriptionCtx);
