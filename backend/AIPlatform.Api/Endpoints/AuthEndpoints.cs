using AIPlatform.Api.Services;

namespace AIPlatform.Api.Endpoints;

/// <summary>
/// Đăng ký, đăng nhập, quên mật khẩu và quản lý người dùng. Gateway chỉ chuyển tiếp;
/// ai-service kiểm tra mật khẩu, OTP, JWT và quyền.
/// </summary>
public static class AuthEndpoints
{
    private static readonly string[] PublicPostPaths =
    {
        "register/start", "register/verify", "register/complete",
        "login",
        "forgot/start", "forgot/verify", "forgot/reset",
    };

    public static IEndpointRouteBuilder MapAuthEndpoints(this IEndpointRouteBuilder app)
    {
        var auth = app.MapGroup("/api/platform/auth");

        foreach (var path in PublicPostPaths)
        {
            var target = "/auth/" + path;
            auth.MapPost("/" + path,
                async (HttpRequest r, IHttpClientFactory f) =>
                    await AiProxy.Post(r, f, target));
        }

        auth.MapGet("/me",
            async (IHttpClientFactory f) => await AiProxy.Get(f, "/auth/me"));

        var users = app.MapGroup("/api/platform/users");

        users.MapGet("",
            async (IHttpClientFactory f) => await AiProxy.Get(f, "/users"));

        users.MapGet("/{userId}",
            async (string userId, IHttpClientFactory f) =>
                await AiProxy.Get(f, $"/users/{Uri.EscapeDataString(userId)}"));

        users.MapPost("/{userId}/password",
            async (string userId, HttpRequest r, IHttpClientFactory f) =>
                await AiProxy.Post(r, f, $"/users/{Uri.EscapeDataString(userId)}/password"));

        users.MapPost("/{userId}/approve",
            async (string userId, IHttpClientFactory f) =>
                await AiProxy.PostEmpty(f, $"/users/{Uri.EscapeDataString(userId)}/approve"));

        users.MapPost("/{userId}/deactivate",
            async (string userId, IHttpClientFactory f) =>
                await AiProxy.PostEmpty(f, $"/users/{Uri.EscapeDataString(userId)}/deactivate"));

        users.MapPost("/{userId}/role",
            async (string userId, HttpRequest r, IHttpClientFactory f) =>
                await AiProxy.Post(r, f, $"/users/{Uri.EscapeDataString(userId)}/role"));

        return app;
    }
}
