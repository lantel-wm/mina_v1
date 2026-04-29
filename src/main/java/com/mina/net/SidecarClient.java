package com.mina.net;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.mina.config.MinaConfig;

import java.io.Closeable;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;

public final class SidecarClient implements Closeable {
	private static final Gson GSON = new Gson();
	private final HttpClient client = HttpClient.newBuilder()
		.version(HttpClient.Version.HTTP_1_1)
		.connectTimeout(Duration.ofSeconds(5))
		.build();

	public CompletableFuture<JsonObject> turn(MinaConfig config, JsonObject payload) {
		return post(config, "/v1/turn", payload);
	}

	public CompletableFuture<JsonObject> actionResults(MinaConfig config, JsonObject payload) {
		return post(config, "/v1/action-results", payload);
	}

	public CompletableFuture<JsonObject> health(MinaConfig config) {
		HttpRequest request = HttpRequest.newBuilder()
			.uri(URI.create(config.sidecarBaseUrl + "/healthz"))
			.version(HttpClient.Version.HTTP_1_1)
			.timeout(Duration.ofMillis(config.sidecarTimeoutMs))
			.GET()
			.build();
		return client.sendAsync(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8))
			.thenApply(SidecarClient::parseResponse);
	}

	private CompletableFuture<JsonObject> post(MinaConfig config, String path, JsonObject payload) {
		HttpRequest request = HttpRequest.newBuilder()
			.uri(URI.create(config.sidecarBaseUrl + path))
			.version(HttpClient.Version.HTTP_1_1)
			.timeout(Duration.ofMillis(config.sidecarTimeoutMs))
			.header("Content-Type", "application/json")
			.POST(HttpRequest.BodyPublishers.ofString(GSON.toJson(payload), StandardCharsets.UTF_8))
			.build();
		return client.sendAsync(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8))
			.thenApply(SidecarClient::parseResponse);
	}

	private static JsonObject parseResponse(HttpResponse<String> response) {
		if (response.statusCode() < 200 || response.statusCode() >= 300) {
			throw new CompletionException(new IllegalStateException("sidecar HTTP " + response.statusCode() + ": " + response.body()));
		}
		return JsonParser.parseString(response.body()).getAsJsonObject();
	}

	@Override
	public void close() {
		// Java's shared HttpClient does not expose explicit shutdown before newer JDK APIs.
	}
}
