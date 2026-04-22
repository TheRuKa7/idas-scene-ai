import { useQuery } from "@tanstack/react-query";
import { Link } from "expo-router";
import { ActivityIndicator, FlatList, Pressable, Text, View } from "react-native";
import { listStreams } from "../../lib/api";
import { Stream } from "../../lib/types";

function statusClass(s: Stream["status"]): string {
  if (s === "running") return "bg-success/20 text-success";
  if (s === "error") return "bg-danger/20 text-danger";
  return "bg-muted/20 text-muted";
}

export default function StreamsScreen() {
  const q = useQuery({ queryKey: ["streams"], queryFn: listStreams });

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
        <Text className="text-danger text-base mb-2">Could not reach the API.</Text>
        <Text className="text-muted text-sm text-center">
          Check the base URL in Settings. On Android emulator, use http://10.0.2.2:8000.
        </Text>
      </View>
    );
  }

  return (
    <FlatList
      className="bg-background"
      contentContainerStyle={{ padding: 16, gap: 12 }}
      data={q.data}
      keyExtractor={(s) => s.id}
      refreshing={q.isRefetching}
      onRefresh={() => q.refetch()}
      ListEmptyComponent={
        <Text className="text-muted text-center mt-16">
          No streams yet. Add one on the server.
        </Text>
      }
      renderItem={({ item }) => (
        <Link href={{ pathname: "/alerts", params: { stream_id: item.id } }} asChild>
          <Pressable className="rounded-2xl border border-border bg-surface p-4 active:opacity-70">
            <View className="flex-row items-center justify-between">
              <Text className="text-white font-semibold text-base">{item.name}</Text>
              <Text className={`px-2 py-0.5 rounded-full text-xs ${statusClass(item.status)}`}>
                {item.status}
              </Text>
            </View>
            <Text className="text-muted text-xs mt-1" numberOfLines={1}>
              {item.url}
            </Text>
            <View className="flex-row gap-4 mt-2">
              <Text className="text-muted text-xs">
                {item.fps ? `${item.fps.toFixed(1)} fps` : "no fps"}
              </Text>
              <Text className="text-muted text-xs">
                {item.active_rules} active rule{item.active_rules === 1 ? "" : "s"}
              </Text>
            </View>
          </Pressable>
        </Link>
      )}
    />
  );
}
