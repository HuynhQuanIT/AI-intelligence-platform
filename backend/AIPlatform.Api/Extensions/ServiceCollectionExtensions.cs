using AIPlatform.Api.Services;

namespace AIPlatform.Api.Extensions;

public static class ServiceCollectionExtensions
{
    /// <summary>HttpClient có tên "ai" trỏ tới ai-service (AiService:BaseUrl).</summary>
    public static IServiceCollection AddAiServiceClient(
        this IServiceCollection services, IConfiguration configuration)
    {
        services.AddHttpClient(AiProxy.ClientName, c =>
        {
            c.BaseAddress = new Uri(
                configuration["AiService:BaseUrl"] ?? "http://localhost:8000");
            c.Timeout = TimeSpan.FromSeconds(90);
        });

        return services;
    }

    public static IServiceCollection AddPlatformCors(this IServiceCollection services)
    {
        services.AddCors(o =>
            o.AddDefaultPolicy(p =>
                p.WithOrigins("http://localhost:5173")
                 .AllowAnyHeader()
                 .AllowAnyMethod()));

        return services;
    }
}
