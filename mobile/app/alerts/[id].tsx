import { useQuery } from "@tanstack/react-query";
import { useLocalSearchParams } from "expo-router";
import { ActivityIndicator, Image, ScrollView, Text, View } from "react-native";
import { getAlert } from "../../lib/api";

export default function AlertDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const q = useQuery({ queryKey: ["alert", id], queryFn: () => getAlert(id!), enabled: !!id });

  if (q.isPending) {
    return (
      <View className="flex-1 items-center justify-center bg-background">
        <ActivityIndicator color="#6366f1" />
      </View>
    );
  }
  if (q.isError || !q.data) {
    return (
      <View className="flex-1 items-center justify-center bg-background p-6">
        <Text className="text-danger">Alert not found.</Text>
      </View>
    );
  }

  const a = q.data;
  const severityColor =
    a.severity === "critical"
      ? "text-danger"
      : a.severity === "warning"
        ? "text-warning"
        : "text-muted";

  return (
    <ScrollView className="bg-background" contentContainerStyle={{ padding: 16, gap: 16 }}>
      <View>
        <Text className={`text-xs uppercase font-semibold ${severityColor}`}>{a.severity}</Text>
        <Text className="text-white text-xl font-semibold mt-1">{a.rule_name}</Text>
        <Text className="text-muted text-xs mt-1">
          Stream {a.stream_id} · {new Date(a.ts).toLocaleString()}
        </Text>
      </View>

      {a.frame_uri ? (
        <Image
          source={{ uri: a.frame_uri }}
          resizeMode="contain"
          className="w-full h-72 rounded-xl border border-border bg-surface"
        />
      ) : (
        <View className="h-72 rounded-xl border border-border bg-surface items-center justify-center">
          <Text className="text-muted">No frame preview</Text>
        </View>
      )}

      {a.explanation ? (
        <View className="rounded-xl border border-border bg-surface p-3">
          <Text className="text-white font-semibold mb-1">Why this fired</Text>
          <Text className="text-muted text-sm leading-5">{a.explanation}</Text>
        </View>
      ) : null}

      <View className="rounded-xl border border-border bg-surface p-3">
        <Text className="text-white font-semibold mb-2">
          Detections ({a.detections.length})
        </Text>
        {a.detections.map((d) => (
          <View
            key={d.id}
            className="flex-row justify-between py-1 border-b border-border last:border-b-0"
          >
            <Text className="text-white">{d.class_name}</Text>
            <Text className="text-muted text-xs">{(d.confidence * 100).toFixed(0)}%</Text>
          </View>
        ))}
      </View>
    </ScrollView>
  );
}
