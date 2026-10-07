using AIPlatform.Api.Services;

namespace AIPlatform.Api.Endpoints;

public static class MonitoringEndpoints
{
    public static IEndpointRouteBuilder MapMonitoringEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/api/platform/agents",
            async (IHttpClientFactory f) => await AiProxy.Get(f, "/agents"));

        app.MapGet("/api/platform/metrics",
            async (IHttpClientFactory f) => await AiProxy.Get(f, "/metrics"));

        app.MapGet("/api/platform/traces",
            async (IHttpClientFactory f) => await AiProxy.Get(f, "/traces"));

        app.MapPost("/api/platform/evaluate",
            async (HttpRequest r, IHttpClientFactory f) =>
                await AiProxy.Post(r, f, "/evaluate"));

        return app;
    }
}
