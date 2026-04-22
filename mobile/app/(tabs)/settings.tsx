import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Alert, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { healthz } from "../../lib/api";
import { useSettings } from "../../lib/store";

export default function SettingsScreen() {
  const { apiBaseUrl, apiKey, setApiBaseUrl, setApiKey } = useSettings();
  const [urlDraft, setUrlDraft] = useState(apiBaseUrl);
  const [keyDraft, setKeyDraft] = useState(apiKey);

  const ping = useMutation({
    mutationFn: healthz,
    onSuccess: (r) => Alert.alert("OK", `Backend v${r.version}`),
    onError: (e: unknown) =>
      Alert.alert("Unreachable", e instanceof Error ? e.message : "Check base URL."),
  });

  return (
    <ScrollView className="bg-background" contentContainerStyle={{ padding: 16, gap: 20 }}>
      <View>
        <Text className="text-white font-semibold mb-2">API base URL</Text>
        <TextInput
          className="rounded-xl border border-border bg-surface text-white px-3 py-3"
          value={urlDraft}
          onChangeText={setUrlDraft}
          placeholder="https://idas.example.com"
          placeholderTextColor="#64748b"
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
        />
        <Text className="text-muted text-xs mt-1">
          Android emulator uses http://10.0.2.2:8000 for localhost. iOS simulator uses
          http://localhost:8000.
        </Text>
      </View>

      <View>
        <Text className="text-white font-semibold mb-2">API key</Text>
        <TextInput
          className="rounded-xl border border-border bg-surface text-white px-3 py-3"
          value={keyDraft}
          onChangeText={setKeyDraft}
          placeholder="optional bearer token"
          placeholderTextColor="#64748b"
          autoCapitalize="none"
          autoCorrect={false}
          secureTextEntry
        />
      </View>

      <View className="flex-row gap-3">
        <Pressable
          className="flex-1 rounded-xl bg-primary py-3 items-center active:opacity-80"
          onPress={() => {
            setApiBaseUrl(urlDraft.trim());
            setApiKey(keyDraft.trim());
            Alert.alert("Saved");
          }}
        >
          <Text className="text-white font-semibold">Save</Text>
        </Pressable>
        <Pressable
          className="flex-1 rounded-xl border border-border py-3 items-center active:opacity-70"
          onPress={() => ping.mutate()}
        >
          <Text className="text-white">
            {ping.isPending ? "Pinging..." : "Test connection"}
          </Text>
        </Pressable>
      </View>

      <View className="mt-6">
        <Text className="text-muted text-xs">
          idas-scene-ai · on-device triage for CCTV and warehouse cameras.
        </Text>
      </View>
    </ScrollView>
  );
}
