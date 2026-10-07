using AIPlatform.Api.Services;

namespace AIPlatform.Api.Endpoints;

public static class SecurityEndpoints
{
    public static IEndpointRouteBuilder MapSecurityEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/api/platform/security/scan",
            async (HttpRequest r, IHttpClientFactory f) =>
                await AiProxy.Post(r, f, "/security/scan"));

        app.MapGet("/api/platform/security/events",
            async (IHttpClientFactory f) => await AiProxy.Get(f, "/security/events"));

        return app;
    }
}
