## Technical Limitations

- Non-APL devices requires a proxied, internet-accessible HTTPS endpoint for the Music Assistant stream
 
  [This means your Music Assistant stream will be publicly accessible on the internet. Take appropriate security measures to protect your Music Assistant instance.]

## Known Issues

### All devices: 
- Skill session does not persist on AlexaPy device commands
- Native Alexa groups are experimental. The companion Music Assistant provider
  can identify Whole Home Audio (`WHA`) devices and target the existing group,
  but Amazon might reject Custom Skill invocation on a virtual group endpoint.
- The Custom Skill `AudioPlayer` API does not provide a synchronization clock,
  group-membership directives, or drift correction. The project must not
  advertise independently launched Echo devices as synchronized playback.
- Alexa and Google Cast devices cannot provide synchronized mixed-protocol
  playback through this skill.

### APL devices:
 - A follow up prompt will continously stay open because of the constant metadata refresh
