package com.dsefa.flir;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;

/** One in-flight frame and one replaceable pending frame; no per-frame executor queue. */
public final class FramePipeline implements AutoCloseable {
    public static final class Result {
        public final int[] raw;
        public final long timestamp;
        public final Thermal.Settings settings;
        public final double[] temperatures;
        public final int[] colors;
        public final String description;
        private Result(Request request,double[] temperatures,int[] colors,String description){
            raw=request.raw;timestamp=request.timestamp;settings=request.settings;
            this.temperatures=temperatures;this.colors=colors;this.description=description;
        }
    }
    private static final class Request {
        final int[] raw;
        final long timestamp,generation;
        final Thermal.Settings settings;
        final boolean render;
        Request(int[] raw,long timestamp,Thermal.Settings settings,boolean render,long generation){
            this.raw=raw;this.timestamp=timestamp;this.settings=settings;this.render=render;this.generation=generation;
        }
    }
    private final Object lock=new Object();
    private final Consumer<Result> sink;
    private final Consumer<String> error;
    private final ExecutorService worker;
    private final Thermal.Renderer renderer=new Thermal.Renderer();
    private long rendererGeneration=Long.MIN_VALUE;
    private Request pending;
    private long generation;
    private boolean scheduled,closed;

    public FramePipeline(Consumer<Result> sink,Consumer<String> error){
        if(sink==null||error==null)throw new IllegalArgumentException("Result and error consumers required");
        this.sink=sink;this.error=error;
        worker=Executors.newSingleThreadExecutor(task->{Thread thread=new Thread(task,"thermal-display");thread.setDaemon(true);return thread;});
    }
    /** Raw is caller-owned immutable storage. Settings are copied before returning. */
    public void submit(int[] raw,long timestamp,Thermal.Settings settings,boolean render){
        synchronized(lock){
            if(closed)return;
            if(raw==null||settings==null)throw new IllegalArgumentException("Frame and settings required");
            pending=new Request(raw,timestamp,settings.copy(),render,generation);
            if(!scheduled){scheduled=true;worker.execute(this::drain);}
        }
    }
    /** Discard pending work and prevent an old in-flight computation from delivering. */
    public void invalidate(){synchronized(lock){generation++;pending=null;}}
    /** Does not wait for processing or a consumer. Consumers should return promptly. */
    @Override public void close(){
        synchronized(lock){if(closed)return;closed=true;generation++;pending=null;}
        worker.shutdownNow();
    }
    private boolean current(Request request){synchronized(lock){return !closed&&generation==request.generation;}}
    private void drain(){
        for(;;){
            Request request;
            synchronized(lock){
                if(closed||pending==null){scheduled=false;return;}
                request=pending;pending=null;
            }
            if(!current(request))continue;
            try{
                if(rendererGeneration!=request.generation){renderer.reset();rendererGeneration=request.generation;}
                double[] temperatures=Thermal.temperatures(request.raw,request.settings);
                if(!current(request))continue;
                int[] colors=request.render?renderer.render(temperatures,request.settings,request.timestamp):null;
                Result result=new Result(request,temperatures,colors,request.render?renderer.description:"Measurements only");
                // Consumers run outside the lock: invalidate/close never waits on UI posting.
                // A consumer that posts to another thread must recheck its own lifecycle token there.
                if(current(request))sink.accept(result);
            }catch(RuntimeException failure){
                renderer.reset();rendererGeneration=Long.MIN_VALUE;
                if(current(request)){
                    String message=failure.getMessage();if(message==null||message.isEmpty())message=failure.getClass().getSimpleName();
                    try{error.accept("Frame processing failed: "+message);}catch(RuntimeException ignored){/* A failed reporter must not terminate capture processing. */}
                }
            }
        }
    }
}
