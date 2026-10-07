using AIPlatform.Api.Services;

namespace AIPlatform.Api.Endpoints;

public static class HealthEndpoints
{
    public static IEndpointRouteBuilder MapHealthEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/health", () =>
            Results.Ok(new { status = "healthy", service = "backend" }));

        app.MapGet("/api/platform/health",
            async (IHttpClientFactory f) => await AiProxy.Get(f, "/health"));

        return app;
    }
}
