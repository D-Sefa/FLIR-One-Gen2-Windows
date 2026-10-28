package com.dsefa.flir;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.Consumer;

/** Deterministic worker/backpressure tests without Android or test-only processor hooks. */
public final class PipelineTest {
    static Class<?> type;
    static void check(boolean condition,String message){if(!condition)throw new AssertionError(message);}
    static void await(CountDownLatch latch,String message)throws Exception{check(latch.await(5,TimeUnit.SECONDS),message);}
    static void hold(CountDownLatch latch){try{latch.await();}catch(InterruptedException e){Thread.currentThread().interrupt();}}
    static Object pipeline(Consumer<Object> sink,Consumer<String> error)throws Exception{return type.getConstructor(Consumer.class,Consumer.class).newInstance(sink,error);}
    static void submit(Object p,int[] raw,long time,Thermal.Settings s,boolean render)throws Exception{type.getMethod("submit",int[].class,long.class,Thermal.Settings.class,boolean.class).invoke(p,raw,time,s,render);}
    static void invoke(Object p,String method)throws Exception{type.getMethod(method).invoke(p);}
    static long timestamp(Object result){try{return result.getClass().getField("timestamp").getLong(result);}catch(Exception e){throw new AssertionError(e);}}
    static Object field(Object result,String name)throws Exception{return result.getClass().getField(name).get(result);}
    public static void main(String[] args)throws Exception{
        try{type=Class.forName("com.dsefa.flir.FramePipeline");}catch(ClassNotFoundException e){throw new AssertionError("Latest-frame background pipeline is missing");}
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1),latest=new CountDownLatch(1);
        List<Object> delivered=Collections.synchronizedList(new ArrayList<Object>());List<String> errors=Collections.synchronizedList(new ArrayList<String>());
        Thread caller=Thread.currentThread();AtomicBoolean offCaller=new AtomicBoolean();
        Object p=pipeline(result->{offCaller.set(Thread.currentThread()!=caller);delivered.add(result);if(timestamp(result)==1){entered.countDown();hold(release);}else latest.countDown();},errors::add);
        int[] raw=new int[19200];Arrays.fill(raw,3000);Thermal.Settings s=new Thermal.Settings();
        try{
            submit(p,raw,1,s,false);await(entered,"First worker did not enter sink");
            for(int i=2;i<=100;i++)submit(p,raw,i,s,false);
            s.offset=12;release.countDown();await(latest,"Latest pending frame did not arrive");
            check(delivered.size()==2&&timestamp(delivered.get(1))==100,"Only newest pending frame should survive replacement");
            check(offCaller.get(),"Radiometry and callbacks must run off submitting thread");
            Object result=delivered.get(1);check(field(result,"raw")==raw,"Raw ownership contract must avoid extra sensor buffer copies");
            check(field(result,"colors")==null,"Measurement-only request must skip render allocation");
            check(Math.abs(((double[])field(result,"temperatures"))[0]-22.513109271244332)<.0001,"Worker uses exact radiometry with submit-time copied settings");
            check(((Thermal.Settings)field(result,"settings")).offset==0,"Pending settings must be defensive snapshots");
            check(errors.isEmpty(),"Valid frames must not report errors");
        }finally{release.countDown();invoke(p,"close");}

        CountDownLatch blocked=new CountDownLatch(1),unblock=new CountDownLatch(1),fresh=new CountDownLatch(1);
        List<Long> stamps=Collections.synchronizedList(new ArrayList<Long>());
        Object generations=pipeline(result->{long stamp=timestamp(result);stamps.add(stamp);if(stamp==1){blocked.countDown();hold(unblock);}else fresh.countDown();},errors::add);
        try{
            submit(generations,raw,1,s,false);await(blocked,"Generation fixture did not block");submit(generations,raw,2,s,false);
            invoke(generations,"invalidate");submit(generations,raw,3,s,true);unblock.countDown();await(fresh,"Fresh generation did not deliver");
            check(stamps.equals(Arrays.asList(1L,3L)),"Invalidation must discard old pending requests");
        }finally{unblock.countDown();invoke(generations,"close");}

        CountDownLatch failed=new CountDownLatch(1),recovered=new CountDownLatch(1);AtomicReference<Object> recoveredResult=new AtomicReference<Object>();
        Object recovering=pipeline(result->{recoveredResult.set(result);recovered.countDown();},message->{check(message!=null&&!message.isEmpty(),"Failures require useful text");failed.countDown();});
        try{
            Thermal.Settings invalid=new Thermal.Settings();invalid.scale="Manual";invalid.low=30;invalid.high=10;
            submit(recovering,raw,1,invalid,true);await(failed,"Invalid render must report an error");
            submit(recovering,raw,2,new Thermal.Settings(),true);await(recovered,"One bad request must not kill worker");
            check(((int[])field(recoveredResult.get(),"colors")).length==19200,"Rendered result must include sensor colors");
            check(!((String)field(recoveredResult.get(),"description")).isEmpty(),"Rendered result must describe mapping");
        }finally{invoke(recovering,"close");}

        CountDownLatch adaptedFirst=new CountDownLatch(1),adaptedSecond=new CountDownLatch(1);AtomicReference<Thread> processingThread=new AtomicReference<Thread>();AtomicReference<Object> adaptedResult=new AtomicReference<Object>();
        Object adapting=pipeline(result->{processingThread.set(Thread.currentThread());if(timestamp(result)==1000)adaptedFirst.countDown();else{adaptedResult.set(result);adaptedSecond.countDown();}},errors::add);
        try{
            Thermal.Settings linear=new Thermal.Settings();linear.scale="Linear auto";linear.palette="White hot";linear.denoise=0;
            submit(adapting,raw,1000,linear,true);await(adaptedFirst,"Adaptive initial frame absent");
            long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);while(processingThread.get().getState()!=Thread.State.WAITING&&System.nanoTime()<deadline)Thread.yield();
            check(processingThread.get().getState()==Thread.State.WAITING,"Worker did not return to idle");
            int[] warmer=new int[19200];Arrays.fill(warmer,3010);linear.offset=0;
            submit(adapting,warmer,1100,linear,true);await(adaptedSecond,"Adaptive next burst absent");
            check((((int[])field(adaptedResult.get(),"colors"))[0]&255)>130,"Renderer must preserve adaptive state between idle bursts");
        }finally{invoke(adapting,"close");}
        CountDownLatch closeEntered=new CountDownLatch(1),closeRelease=new CountDownLatch(1),closed=new CountDownLatch(1);AtomicInteger closeCalls=new AtomicInteger();AtomicReference<Thread> closingThread=new AtomicReference<Thread>();
        Object closing=pipeline(result->{closingThread.set(Thread.currentThread());closeCalls.incrementAndGet();closeEntered.countDown();hold(closeRelease);},errors::add);
        submit(closing,raw,1,s,false);await(closeEntered,"Close fixture did not block");submit(closing,raw,2,s,false);
        Thread closer=new Thread(()->{try{invoke(closing,"close");closed.countDown();}catch(Exception e){throw new AssertionError(e);}});closer.start();
        await(closed,"Close must not block on sink completion");submit(closing,raw,3,s,false);closeRelease.countDown();closer.join();closingThread.get().join(5000);check(!closingThread.get().isAlive(),"Closed worker must terminate without leaking a thread");
        check(closeCalls.get()==1,"Close must suppress queued frames and subsequent submits");invoke(closing,"close");
        System.out.println("PASS latest-frame bounded queue / copied settings / worker radiometry / invalidation / recovery / nonblocking close");
    }
}
