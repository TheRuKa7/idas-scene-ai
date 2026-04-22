import { useQuery } from "@tanstack/react-query";
import { Link, useLocalSearchParams } from "expo-router";
import { ActivityIndicator, FlatList, Pressable, Text, View } from "react-native";
import { listAlerts } from "../../lib/api";
import { RuleHit } from "../../lib/types";

function severityClass(s: RuleHit["severity"]): string {
  if (s === "critical") return "bg-danger/20 text-danger";
  if (s === "warning") return "bg-warning/20 text-warning";
  return "bg-muted/20 text-muted";
}

function relativeTime(iso: string): string {
  const d = new Date(iso).getTime();
  const delta = Date.now() - d;
  const m = Math.floor(delta / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function AlertsScreen() {
  const params = useLocalSearchParams<{ stream_id?: string }>();
  const q = useQuery({
    queryKey: ["alerts", params.stream_id ?? "all"],
    queryFn: () =>
      listAlerts(params.stream_id ? { stream_id: params.stream_id, limit: 50 } : { limit: 50 }),
  });

  if (q.isPending) {
    return (
      <View className="flex-1 items-center justify-center bg-background">
        <ActivityIndicator color="#6366f1" />
      </View>
    );
  }
  if (q.isError) {
    return (
      <View className="flex-1 items-center justify-center bg-background p-6">
        <Text className="text-danger">Failed to load alerts.</Text>
      </View>
    );
  }

  return (
    <FlatList
      className="bg-background"
      contentContainerStyle={{ padding: 16, gap: 10 }}
      data={q.data}
      keyExtractor={(a) => a.id}
      refreshing={q.isRefetching}
      onRefresh={() => q.refetch()}
      ListEmptyComponent={
        <Text className="text-muted text-center mt-16">No alerts yet. You're all clear.</Text>
      }
      renderItem={({ item }) => (
        <Link href={{ pathname: "/alerts/[id]", params: { id: item.id } }} asChild>
          <Pressable className="rounded-xl border border-border bg-surface p-3 active:opacity-70">
            <View className="flex-row items-center justify-between">
              <Text className="text-white font-medium">{item.rule_name}</Text>
              <Text className={`px-2 py-0.5 rounded-full text-xs ${severityClass(item.severity)}`}>
                {item.severity}
              </Text>
            </View>
            <View className="flex-row items-center justify-between mt-1">
              <Text className="text-muted text-xs">{relativeTime(item.ts)}</Text>
              <Text className="text-muted text-xs">
                {item.detections.length} detection{item.detections.length === 1 ? "" : "s"}
              </Text>
            </View>
          </Pressable>
        </Link>
      )}
    />
  );
}
