package com.dsefa.flir;
final class ChromeState {private long last;void touch(long now){last=now;}boolean hidden(long now){return now-last>=4000;}}
