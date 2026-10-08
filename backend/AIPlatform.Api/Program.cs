using AIPlatform.Api.Endpoints;
using AIPlatform.Api.Extensions;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();
builder.Services.AddAiServiceClient(builder.Configuration);
builder.Services.AddPlatformCors();

var app = builder.Build();

app.UseCors();

if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.MapHealthEndpoints();
app.MapAuthEndpoints();
app.MapChatEndpoints();
app.MapConversationEndpoints();
app.MapDocumentEndpoints();
app.MapMonitoringEndpoints();
app.MapSecurityEndpoints();

app.Run();
